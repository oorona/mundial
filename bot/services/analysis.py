import spacy
import structlog
import random
import json
from langdetect import detect
from typing import Dict, Any, Optional

logger = structlog.get_logger()

class AnalysisService:
    def __init__(self, llm_service, redis_client):
        self.llm = llm_service
        self.redis = redis_client
        self.nlp_en = None
        self.nlp_es = None
        self._load_models()

    def _load_models(self):
        try:
            self.nlp_en = spacy.load("en_core_web_sm")
            self.nlp_es = spacy.load("es_core_news_sm")
            logger.info("spacy_models_loaded")
        except Exception as e:
            logger.error("spacy_load_failed", error=str(e))

    def detect_language(self, text: str) -> str:
        try:
            return detect(text)
        except Exception:
            return "en" # Default fallback

    def is_meaningful(self, text: str) -> bool:
        """
        Check if message is meaningful enough for analysis.
        Criteria:
        - Length > 10 chars
        - Contains at least one noun and one verb
        """
        if len(text) < 10:
            return False

        lang = self.detect_language(text)
        nlp = self.nlp_es if lang == 'es' else self.nlp_en
        
        if not nlp:
            return True # Fallback if models failed to load

        doc = nlp(text)
        has_noun = any(token.pos_ == "NOUN" for token in doc)
        has_verb = any(token.pos_ == "VERB" for token in doc)
        
        return has_noun and has_verb

    async def analyze_background(self, user_id: int, text: str):
        """
        Run background analysis pipeline.
        """
        if not self.is_meaningful(text):
            return

        # 1. Memory Analysis (Random 30% chance)
        if random.random() < 0.3:
            await self._analyze_memory(user_id, text)

        # 2. Sentiment Analysis (Always for meaningful messages)
        await self._analyze_sentiment(user_id, text)

        # 3. Personality Analysis (Always for meaningful messages)
        await self._analyze_personality(user_id, text)

    async def _analyze_memory(self, user_id: int, text: str):
        prompt = f"Extract any important facts about the user from this message: '{text}'. Return JSON with a list of facts."
        schema = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "string"}}}}
        
        try:
            result = await self.llm.generate_structured(prompt, schema, system_prompt="You are a memory extraction system.")
            facts = result.get("facts", [])
            if facts:
                key = f"memory:{user_id}"
                for fact in facts:
                    await self.redis.rpush(key, fact)
                logger.info("memory_extracted", user_id=user_id, count=len(facts))
        except Exception as e:
            logger.error("memory_analysis_failed", error=str(e))

    async def _analyze_sentiment(self, user_id: int, text: str):
        prompt = f"Analyze the sentiment of this message: '{text}'. Return JSON with 'sentiment' (positive, negative, neutral) and 'score' (0.0 to 1.0)."
        schema = {
            "type": "object", 
            "properties": {
                "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
                "score": {"type": "number"}
            }
        }
        
        try:
            result = await self.llm.generate_structured(prompt, schema, system_prompt="You are a sentiment analysis system.")
            # Store or log? For now log
            logger.info("sentiment_analyzed", user_id=user_id, result=result)
        except Exception as e:
            logger.error("sentiment_analysis_failed", error=str(e))

    async def _analyze_personality(self, user_id: int, text: str):
        prompt = f"Analyze the personality of the user based on this message: '{text}'. Rate on 7 dimensions (1-10): Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism, Creativity, Empathy. Return JSON."
        schema = {
            "type": "object",
            "properties": {
                "openness": {"type": "integer"},
                "conscientiousness": {"type": "integer"},
                "extraversion": {"type": "integer"},
                "agreeableness": {"type": "integer"},
                "neuroticism": {"type": "integer"},
                "creativity": {"type": "integer"},
                "empathy": {"type": "integer"}
            }
        }
        
        try:
            result = await self.llm.generate_structured(prompt, schema, system_prompt="You are a personality analysis system.")
            logger.info("personality_analyzed", user_id=user_id, result=result)
        except Exception as e:
            logger.error("personality_analysis_failed", error=str(e))
