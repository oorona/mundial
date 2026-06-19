import axios, { AxiosError, AxiosInstance } from 'axios';

// Network Topology & API Routing:
// 1. Client-Side (Browser): Uses relative path '' to hit Next.js Frontend Proxy (which routes /api/v1 -> Backend).
// 2. Server-Side (SSR): Next.js Server (Container) must hit Backend Container directly via Docker Network (http://backend:8000).
const IS_SERVER = typeof window === 'undefined';
const API_BASE_URL = IS_SERVER
    ? (process.env.INTERNAL_API_URL || 'http://backend:8000')
    : (process.env.NEXT_PUBLIC_API_URL || '');

export interface DiscordUser {
    id: string;
    username: string;
    discriminator: string;
    avatar_url: string;
    bot?: boolean;
    preferences?: UserSettings;
}

export interface UserSettings {
    theme?: 'light' | 'dark' | 'system';
    language?: 'en' | 'es';
    default_guild_id?: string;
}

export interface DiscordMember {
    id: string;
    username: string;
    discriminator: string;
    avatar_url: string | null;
    roles: string[];
}

export interface AuthorizedUser {
    user_id: string;
    permission_level: string;
    created_at: string;
}

export interface SettingsFieldChoice {
    label: string;
    value: string;
}

export interface SettingsField {
    key: string;
    type:
        | 'boolean'
        | 'channel_select'
        | 'role_select'
        | 'multiselect'
        | 'text'
        | 'number'
        | 'color'        // single hex color
        | 'color_list'   // ordered palette of N colors
        | 'select';      // single-choice enum
    label: string;
    description?: string;
    default: boolean | string | number | string[] | null;
    choices?: SettingsFieldChoice[];
    options?: SettingsFieldChoice[]; // alias accepted for 'select'
    // Numeric constraints ('number')
    min?: number;
    max?: number;
    step?: number;
    // Palette length ('color_list')
    count?: number;
}

export interface SettingsSchema {
    id: string;
    label: string;
    description: string;
    fields: SettingsField[];
}

export interface LLMRequest {
    prompt: string;
    system_prompt?: string;
    provider?: string;
    model?: string;
    guild_id?: number;
}

export interface ModelPricing {
    id?: number;
    provider: string;
    model: string;
    input_cost_per_1k: number;
    output_cost_per_1k: number;
    cached_cost_per_1k: number;
    image_cost: number;
    audio_cost_per_minute: number;
    is_active?: boolean;
}

export interface ChatRequest {
    message: string;
    context_id: string;
    name?: string;
    provider?: string;
    model?: string;
    guild_id?: number;
}

// Caller-defined tool the LLM may choose to call (provider-agnostic).
export interface LLMToolDef {
    name: string;
    description?: string;
    parameters?: Record<string, unknown>;
}

// Body for the guild-scoped / Activity LLM endpoints.
export interface GuildLLMRequest {
    prompt: string;
    system_prompt?: string;
    provider?: string;
    model?: string;
    tools?: LLMToolDef[];
}

// Discriminated union returned by the guild-scoped / Activity LLM endpoints.
export interface LLMResult {
    type: 'message' | 'tool_call';
    content?: string;                          // when type === 'message'
    function?: string;                         // when type === 'tool_call'
    arguments?: Record<string, unknown>;       // when type === 'tool_call'
}

export interface AuthorizedRole {
    id: number;
    guild_id: string;
    role_id: string;
    permission_level: string;
    created_at: string;
}



// In-memory auth token. Discord Activity iframes have unreliable / partitioned
// localStorage, so the activity handshake sets the token here and the request
// interceptor prefers it over localStorage. Lives only for the page's lifetime,
// which is fine: each activity page re-runs the handshake on load.
let inMemoryToken: string | null = null;
export function setAuthToken(token: string | null) { inMemoryToken = token; }

class APIClient {
    private client: AxiosInstance;

    constructor() {
        this.client = axios.create({
            baseURL: `${API_BASE_URL}/api/v1`,
            headers: {
                'Content-Type': 'application/json',
            },
            withCredentials: true, // For session cookies
        });

        // Request interceptor
        this.client.interceptors.request.use(
            (config) => {
                // Prefer the in-memory token (Discord Activity), fall back to localStorage (dashboard).
                const token = inMemoryToken || (typeof window !== 'undefined' ? localStorage.getItem('access_token') : null);
                if (token) {
                    config.headers.Authorization = `Bearer ${token}`;
                }
                return config;
            },
            (error) => Promise.reject(error)
        );

        // Response interceptor
        this.client.interceptors.response.use(
            (response) => {
                // If login response contains session_id, store it
                if (response.config.url?.includes('/auth/discord/callback') && response.data.session_id) {
                    if (typeof window !== 'undefined') {
                        localStorage.setItem('access_token', response.data.session_id);
                    }
                }
                return response;
            },
            async (error: AxiosError) => {
                // Inside a Discord Activity (/activity/*), a transient 401/403 must
                // NOT wipe the activity token or redirect the iframe to the dashboard
                // /login or /access-denied (those aren't framable) — that breaks the
                // activity. Just surface the error so the page can handle it.
                const inActivity = typeof window !== 'undefined' && window.location.pathname.startsWith('/activity');
                if (error.response?.status === 401) {
                    // Special case: Don't redirect if we are just checking auth status
                    // This allows public pages to load without forcing login
                    if (error.config?.url?.includes('/auth/me') || inActivity) {
                        return Promise.reject(error);
                    }

                    // Unauthorized - clear token and redirect to login
                    if (typeof window !== 'undefined') {
                        localStorage.removeItem('access_token');
                        if (window.location.pathname !== '/login') {
                            window.location.href = '/login';
                        }
                    }
                } else if (error.response?.status === 403) {
                    // Forbidden - redirect to access denied page
                    if (typeof window !== 'undefined' && !inActivity) {
                        if (window.location.pathname !== '/access-denied') {
                            window.location.href = '/access-denied';
                        }
                    }
                }
                return Promise.reject(error);
            }
        );
    }

    // Auth endpoints
    async getCurrentUser() {
        const response = await this.client.get('/auth/me');
        return response.data;
    }

    // Discord Activity (Embedded App SDK) handshake. Exchanges an SDK OAuth
    // code + the instance guild_id for a short-lived activity session token.
    async activityAuth(code: string, guildId: string) {
        const response = await this.client.post('/auth/activity', { code, guild_id: guildId });
        return response.data;
    }

    async logout() {
        const response = await this.client.post('/auth/logout');
        if (typeof window !== 'undefined') {
            localStorage.removeItem('access_token');
        }
        return response.data;
    }

    async logoutAll() {
        const response = await this.client.post('/auth/logout-all');
        if (typeof window !== 'undefined') {
            localStorage.removeItem('access_token');
        }
        return response.data;
    }

    // User Settings
    async getUserSettings() {
        const response = await this.client.get('/users/me/settings');
        return response.data;
    }

    async updateUserSettings(settings: UserSettings) {
        const response = await this.client.put('/users/me/settings', settings);
        return response.data;
    }

    // Guild endpoints
    async getGuilds() {
        const response = await this.client.get('/guilds');
        return response.data;
    }

    async getGuildPublicInfo(guildId: string) {
        const response = await this.client.get(`/guilds/${guildId}/public`);
        return response.data;
    }

    // Public site surface (Level 0/1 — no auth). Methods below never require a
    // token; the request interceptor simply no-ops when none is present.
    async getProjectInfo() {
        const response = await this.client.get('/public/project');
        return response.data;
    }

    async getPublicSite(slug: string) {
        const response = await this.client.get(`/public/site/${slug}`);
        return response.data;
    }

    async setGuildSlug(guildId: string, slug: string) {
        const response = await this.client.put(`/guilds/${guildId}/slug`, { slug });
        return response.data;
    }

    async getGuild(guildId: string) {
        const response = await this.client.get(`/guilds/${guildId}`);
        return response.data;
    }

    // Settings endpoints
    async getGuildSettings(guildId: string) {
        const response = await this.client.get(`/guilds/${guildId}/settings`);
        return response.data;
    }

    async updateGuildSettings(guildId: string, settings: Record<string, any>) {
        const response = await this.client.put(`/guilds/${guildId}/settings`, { settings });
        return response.data;
    }

    async getPlatformSettings() {
        const response = await this.client.get('/platform/settings');
        return response.data;
    }

    async updatePlatformSettings(settings: Record<string, any>) {
        const response = await this.client.put('/platform/settings', { settings });
        return response.data;
    }

    async getDbStatus() {
        const response = await this.client.get('/platform/db-status');
        return response.data;
    }

    async getFrontendStatus() {
        const response = await this.client.get('/platform/frontend-status');
        return response.data;
    }

    async getBackendStatus() {
        const response = await this.client.get('/platform/backend-status');
        return response.data;
    }

    // Comprehensive platform status: component health + per-guild + user totals (Developer).
    async getPlatformOverview() {
        const response = await this.client.get('/platform/overview');
        return response.data;
    }

    async getGuildChannels(guildId: string) {
        const response = await this.client.get(`/guilds/${guildId}/channels`);
        return response.data;
    }

    async getGuildRoles(guildId: string): Promise<any[]> {
        const response = await this.client.get(`/guilds/${guildId}/roles`);
        return response.data;
    }

    async searchGuildMembers(guildId: string, query: string): Promise<any[]> {
        const response = await this.client.get(`/guilds/${guildId}/members/search`, {
            params: { query }
        });
        return response.data;
    }


    // Permission endpoints
    async getAuthorizedUsers(guildId: string): Promise<AuthorizedUser[]> {
        const response = await this.client.get(`/guilds/${guildId}/authorized-users`);
        return response.data;
    }

    async addAuthorizedUser(guildId: string, userId: string) {
        const response = await this.client.post(`/guilds/${guildId}/authorized-users`, { user_id: userId });
        return response.data;
    }

    async removeAuthorizedUser(guildId: string, userId: string) {
        const response = await this.client.delete(`/guilds/${guildId}/authorized-users/${userId}`);
        return response.data;
    }

    async getAuthorizedRoles(guildId: string): Promise<AuthorizedRole[]> {
        const response = await this.client.get(`/guilds/${guildId}/authorized-roles`);
        return response.data;
    }

    async addAuthorizedRole(guildId: string, roleId: string) {
        const response = await this.client.post(`/guilds/${guildId}/authorized-roles`, { role_id: roleId });
        return response.data;
    }

    async removeAuthorizedRole(guildId: string, roleId: string) {
        const response = await this.client.delete(`/guilds/${guildId}/authorized-roles/${roleId}`);
        return response.data;
    }

    async getDiscordConfig(): Promise<{ client_id: string; redirect_uri: string }> {
        const response = await this.client.get('/auth/discord-config');
        return response.data;
    }

    async getAuditLogs(guildId: string) {
        const response = await this.client.get(`/guilds/${guildId}/audit-logs`);
        return response.data;
    }

    async purgeAuditLogs(guildId: string, params: { older_than_days?: number; before?: string; after?: string }) {
        const response = await this.client.delete(`/guilds/${guildId}/audit-logs`, { params });
        return response.data as { deleted: number };
    }

    // Shard endpoints
    async getShards() {
        const response = await this.client.get('/shards');
        return response.data;
    }

    async getShardForGuild(guildId: string) {
        const response = await this.client.get(`/shards/${guildId}`);
        return response.data;
    }

    // Bot endpoints
    async getBotReport() {
        const response = await this.client.get('/bot/report');
        return response.data;
    }

    // LLM endpoints
    async generateText(request: LLMRequest) {
        const response = await this.client.post('/llm/generate', request);
        return response.data;
    }

    async chat(request: ChatRequest) {
        const response = await this.client.post('/llm/chat', request);
        return response.data;
    }

    // Tracked image generation. Returns { urls?|images?(base64), count, model }.
    async generateImage(request: { prompt: string; provider?: string; model?: string; n?: number; guild_id?: number }) {
        const response = await this.client.post('/llm/image', request);
        return response.data as { urls?: string[]; images?: string[]; count: number; model: string };
    }

    // Tracked embeddings. Returns the embedding vector(s).
    async embed(request: { input: string | string[]; provider?: string; model?: string; guild_id?: number }) {
        const response = await this.client.post('/llm/embed', request);
        return (response.data as { embeddings: number[][] }).embeddings;
    }

    // Guild-scoped LLM (logged-in guild member). Tracked + attributed to the guild.
    // Pass `tools` to let the model return a tool_call for the app to execute.
    async guildGenerateText(guildId: string, body: GuildLLMRequest): Promise<LLMResult> {
        const response = await this.client.post(`/guilds/${guildId}/llm/generate`, body);
        return response.data;
    }

    // Discord Activity LLM (authed by the activity session). Tracked + guild-attributed.
    async activityGenerateText(guildId: string, body: GuildLLMRequest): Promise<LLMResult> {
        const response = await this.client.post(`/guilds/${guildId}/llm/activity/generate`, body);
        return response.data;
    }

    async getLLMStats() {
        const response = await this.client.get('/llm/stats');
        return response.data;
    }

    // Available models per configured provider — feeds the System Config model picker.
    async getLLMModels(): Promise<Record<string, string[]>> {
        const response = await this.client.get('/llm/models');
        return response.data;
    }

    async purgeLLMUsage(params: { older_than_days?: number; before?: string; after?: string }) {
        const response = await this.client.delete('/llm/usage', { params });
        return response.data as { deleted: number; summaries_deleted: number };
    }

    // Model Pricing (Developer) — view/edit the llm_model_pricing rows that drive cost tracking.
    async listModelPricing(): Promise<{ pricing: ModelPricing[] }> {
        const response = await this.client.get('/llm/pricing');
        return response.data;
    }

    async upsertModelPricing(body: ModelPricing): Promise<ModelPricing> {
        const response = await this.client.post('/llm/pricing', body);
        return response.data;
    }

    async deleteModelPricing(id: number): Promise<{ deleted: number }> {
        const response = await this.client.delete(`/llm/pricing/${id}`);
        return response.data;
    }

    // *** DEMO CODE *** - Gemini Demo Endpoints
    // Full documentation: https://ai.google.dev/gemini-api/docs
    
    /**
     * Generate text with Gemini models supporting thinking/reasoning.
     * 
     * @description Supports all Gemini 3 and 2.5 models with configurable thinking levels.
     * Thinking tokens allow the model to reason before responding, improving accuracy
     * for complex tasks. Thinking tokens are billed at output token rates.
     * 
     * Models available:
     * - gemini-3-flash-preview: Fast, thinking levels: minimal, low, medium, high ($0.50/$3 per 1M)
     * - gemini-3-pro-preview: Most capable, thinking levels: low, high ($2/$12 per 1M)
     * - gemini-2.5-flash: Budget-friendly with thinking ($0.15/$0.60 per 1M)
     * - gemini-2.5-pro: Powerful reasoning ($1.25/$10 per 1M)
     * 
     * @see https://ai.google.dev/gemini-api/docs/thinking
     */
    async geminiGenerate(request: {
        /** The prompt/query to send to the model */
        prompt: string;
        /** Thinking level: 'minimal' | 'low' | 'medium' | 'high' (Gemini 3 only) */
        thinking_level?: string;
        /** Optional token budget for thinking (overrides thinking_level) */
        thinking_budget?: number;
        /** Model to use (defaults to gemini-2.5-flash) */
        model?: string;
        /** Include model's thinking summary in response */
        include_thoughts?: boolean;
        /** System instruction/persona for the model */
        system_instruction?: string;
        /** Temperature 0-2 (default 1.0, recommended to keep at 1.0 for Gemini 3) */
        temperature?: number;
        /** Maximum output tokens */
        max_tokens?: number;
        /** Guild ID for logging/analytics */
        guild_id?: string;
    }) {
        const response = await this.client.post('/gemini/generate', request);
        return response.data;
    }

    /**
     * Count tokens in content before sending to API.
     * 
     * @description Use this to estimate costs and ensure content fits within context limits.
     * Token costs vary by content type:
     * - Text: ~4 characters per token for English
     * - Images: 258 tokens (<384px) to 768 tokens (>768px)
     * - Audio: 32 tokens per second
     * - Video: 263 tokens/second (video) + 32 tokens/second (audio track)
     * 
     * @see https://ai.google.dev/gemini-api/docs/tokens
     */
    async geminiCountTokens(request: { 
        /** The text content to count tokens for */
        content: string; 
        /** Model for tokenization (different models may tokenize differently) */
        model?: string;
        /** Include system instruction in count */
        system_instruction?: string;
        /** Include tools/function definitions in count */
        tools?: any[];
        /** Include chat history in count */
        chat_history?: { role: string; content: string }[];
        /** Return detailed model information */
        include_model_info?: boolean;
    }) {
        const response = await this.client.post('/gemini/count-tokens', request);
        return response.data;
    }

    /**
     * Estimate token count for multimodal content (images, video, audio).
     * 
     * @description Provides token estimates based on media dimensions and duration.
     * Useful for cost estimation before uploading large media files.
     * 
     * Token rates:
     * - Images: 258 tokens (small) to 768 tokens (large)
     * - Audio: 32 tokens per second (max 9.5 hours)
     * - Video: ~263 tokens/second + audio track tokens
     */
    async geminiEstimateMultimodalTokens(request: {
        /** Type of media: 'image' | 'video' | 'audio' */
        media_type: 'image' | 'video' | 'audio';
        /** Image/video width in pixels */
        width?: number;
        /** Image/video height in pixels */
        height?: number;
        /** Duration in seconds for audio/video */
        duration_seconds?: number;
        /** For video: count only audio track tokens */
        audio_only?: boolean;
    }) {
        const response = await this.client.post('/gemini/estimate-multimodal-tokens', request);
        return response.data;
    }

    /**
     * Get detailed information about a specific model.
     * 
     * @description Returns model capabilities, context window, pricing, and supported features.
     */
    async geminiModelInfo(modelName: string) {
        const response = await this.client.get(`/gemini/model-info/${modelName}`);
        return response.data;
    }

    /**
     * Generate structured JSON output with schema validation.
     * 
     * @description Forces the model to output valid JSON matching a specified schema.
     * Supports predefined schemas, custom JSON schemas, enum classification, and tool integration.
     * 
     * **Modes:**
     * - Predefined: Use schema_name (person, recipe, article, review, feedback, event, product, sentiment, language, intent)
     * - Custom: Provide custom_schema with schema_name='custom'
     * - Enum: Use enum_values for simple classification
     * 
     * **Features:**
     * - Guaranteed valid JSON output
     * - Schema validation
     * - Tool integration (Google Search, URL Context) for Gemini 3
     * - Nullable field support
     * - Array/number constraints
     * 
     * @see https://ai.google.dev/gemini-api/docs/structured-output
     */
    async geminiStructured(request: { 
        /** The text to extract structured data from */
        prompt: string; 
        /** Predefined schema name: person, recipe, article, review, feedback, event, product, sentiment, language, intent, custom */
        schema_name?: string;
        /** Custom JSON Schema (required when schema_name='custom') */
        custom_schema?: Record<string, unknown>;
        /** Model: gemini-3-flash-preview (recommended), gemini-3-pro-preview, gemini-2.5-flash, gemini-2.5-pro */
        model?: string;
        /** Simple enum classification: output constrained to one of these values */
        enum_values?: string[];
        /** Type for enum mode: 'string' | 'integer' | 'number' */
        enum_type?: string;
        /** Combine with tools: 'google_search', 'url_context' (Gemini 3 only) */
        use_tools?: string[];
        /** Enforce strict schema validation */
        strict_mode?: boolean;
        /** Allow null values for optional fields */
        include_null?: boolean;
        /** Explicit property order (required for Gemini 2.0/2.5) */
        property_ordering?: string[];
        /** Include the resolved schema in response */
        return_schema?: boolean;
        /** Validate response against schema before returning */
        validate_response?: boolean;
    }) {
        const response = await this.client.post('/gemini/structured', request);
        return response.data;
    }

    /**
     * Get list of all available predefined schemas for structured output.
     * 
     * Returns schema definitions with their structure, required fields, and usage examples.
     * Use this to understand what schemas are available and their expected output format.
     * 
     * @see https://ai.google.dev/gemini-api/docs/structured-output
     */
    async geminiStructuredSchemas() {
        const response = await this.client.get('/gemini/structured/schemas');
        return response.data;
    }

    /**
     * Get list of all available Gemini capabilities and models.
     */
    async geminiCapabilities() {
        const response = await this.client.get('/gemini/capabilities');
        return response.data;
    }

    /**
     * Generate images from text prompts using Gemini's native image generation (Nano Banana).
     * 
     * @description Text-to-image generation with advanced features including:
     * - Multiple aspect ratios (1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9)
     * - High resolution output (1K, 2K, 4K for Pro model)
     * - Google Search grounding for real-time data (Pro model only)
     * - Thinking process visualization (Pro model only)
     * 
     * Models:
     * - gemini-2.5-flash-image: Fast generation, 1024px max, optimized for speed
     * - gemini-3-pro-image-preview: Professional quality, up to 4K, with thinking
     * 
     * Prompting Best Practices:
     * - Describe scenes narratively rather than listing keywords
     * - Use photography terms for realism: "wide-angle shot", "macro", "low-angle"
     * - Be hyper-specific about details, lighting, and composition
     * - Use semantic negative prompts: describe what you want, not what to avoid
     * 
     * @see https://ai.google.dev/gemini-api/docs/image-generation
     */
    async geminiImageGenerate(request: { 
        /** Detailed description of the image to generate. Use descriptive paragraphs, not keywords. */
        prompt: string; 
        /** Model: 'gemini-2.5-flash-image' (fast) or 'gemini-3-pro-image-preview' (pro, up to 4K) */
        model?: string;
        /** Aspect ratio: '1:1' | '2:3' | '3:2' | '3:4' | '4:3' | '4:5' | '5:4' | '9:16' | '16:9' | '21:9' */
        aspect_ratio?: string;
        /** Image size for Pro model only: '1K' | '2K' | '4K'. Must be uppercase. */
        image_size?: string;
        /** Include text in response (default: true). Set false for image-only output. */
        include_text?: boolean;
        /** Enable Google Search grounding for real-time data (Pro model only) */
        use_google_search?: boolean;
        /** Include thinking/interim images in response (Pro model only) */
        include_thoughts?: boolean;
    }) {
        // Extended timeout for image generation (can take 30-60s)
        const response = await this.client.post('/gemini/image-generate', request, {
            timeout: 120000, // 2 minutes
        });
        return response.data;
    }

    /**
     * Edit images using text prompts (text+image-to-image).
     * 
     * @description Image editing capabilities including:
     * - Add/remove elements from images
     * - Inpainting (semantic masking) - edit specific parts while preserving others
     * - Style transfer - recreate content in different artistic styles
     * - Color grading and lighting adjustments
     * 
     * Prompting Tips:
     * - "Using the provided image, change only [element] to [new element]"
     * - "Keep everything else exactly the same, preserving style and lighting"
     * - "Add [element] to the [position] of the scene"
     * 
     * @see https://ai.google.dev/gemini-api/docs/image-generation#image-editing
     */
    async geminiImageEdit(request: {
        /** Edit instruction (e.g., "Add a red hat to the person") */
        prompt: string;
        /** URL of the base image to edit */
        image_url: string;
        /** Model: 'gemini-2.5-flash-image' or 'gemini-3-pro-image-preview' */
        model?: string;
        /** Aspect ratio: '1:1' | '2:3' | '3:2' | '3:4' | '4:3' | '4:5' | '5:4' | '9:16' | '16:9' | '21:9' */
        aspect_ratio?: string;
        /** Image size for Pro model: '1K' | '2K' | '4K' */
        image_size?: string;
    }) {
        // Extended timeout for image editing (can take 30-60s)
        const response = await this.client.post('/gemini/image-edit', request, {
            timeout: 120000, // 2 minutes
        });
        return response.data;
    }

    /**
     * Compose images from multiple reference images (up to 14).
     * 
     * @description Multi-image composition for complex creations:
     * - Combine elements from multiple source images
     * - Character consistency across multiple images (up to 5 humans)
     * - Object fidelity for product mockups (up to 6 objects)
     * - Total up to 14 reference images with Pro model
     * 
     * Model Limits:
     * - gemini-2.5-flash-image: Best with up to 3 images
     * - gemini-3-pro-image-preview: Up to 14 images (5 humans + 6 objects + extras)
     * 
     * @see https://ai.google.dev/gemini-api/docs/image-generation#use-up-to-14-reference-images
     */
    async geminiImageCompose(request: {
        /** Composition instruction describing the final image */
        prompt: string;
        /** List of image URLs to use as references */
        image_urls: string[];
        /** Model: 'gemini-2.5-flash-image' or 'gemini-3-pro-image-preview' */
        model?: string;
        /** Aspect ratio: '1:1' | '2:3' | '3:2' | '3:4' | '4:3' | '4:5' | '5:4' | '9:16' | '16:9' | '21:9' */
        aspect_ratio?: string;
        /** Image size for Pro model: '1K' | '2K' | '4K' */
        image_size?: string;
    }) {
        // Extended timeout for multi-image composition (can take 30-90s)
        const response = await this.client.post('/gemini/image-compose', request, {
            timeout: 120000, // 2 minutes
        });
        return response.data;
    }

    /**
     * Analyze and understand image content.
     * 
     * @description Uses Gemini's vision capabilities to analyze images.
     * Can describe content, extract text (OCR), answer questions about images.
     * 
     * Token calculation:
     * - 258 tokens if both dimensions ≤ 384px
     * - Larger images tiled into 768x768 tiles at 258 tokens each
     * 
     * @see https://ai.google.dev/gemini-api/docs/image-understanding
     */
    async geminiImageUnderstand(request: { 
        /** URL of the image to analyze */
        image_url: string; 
        /** Question or instruction about the image */
        prompt?: string;
        /** Model: gemini-3-flash-preview, gemini-3-pro-preview */
        model?: string;
        /** Media resolution: low, medium, high, ultra_high (Gemini 3 only) */
        media_resolution?: string;
    }) {
        const response = await this.client.post('/gemini/image-understand', request);
        return response.data;
    }

    /**
     * Detect objects in an image with bounding boxes.
     * 
     * @description Get bounding box coordinates for objects in an image.
     * Coordinates are normalized to 0-1000 scale: [ymin, xmin, ymax, xmax].
     * 
     * To convert to pixels:
     * - abs_x1 = int(box_2d[1] / 1000 * image_width)
     * - abs_y1 = int(box_2d[0] / 1000 * image_height)
     * 
     * @see https://ai.google.dev/gemini-api/docs/image-understanding#object-detection
     */
    async geminiImageDetect(request: {
        /** URL of the image to analyze */
        image_url: string;
        /** Detection prompt (e.g., 'Detect all green objects') */
        prompt?: string;
        /** Model: gemini-3-flash-preview, gemini-3-pro-preview */
        model?: string;
        /** Media resolution: low, medium, high, ultra_high */
        media_resolution?: string;
    }) {
        const response = await this.client.post('/gemini/image-detect', request);
        return response.data;
    }

    /**
     * Segment objects in an image with contour masks.
     * 
     * @description Get segmentation masks for objects in an image.
     * Returns bounding boxes and base64 PNG masks (probability maps 0-255).
     * Threshold masks at 127 for binary segmentation.
     * 
     * @note This operation can take 30-120 seconds for complex images.
     * Uses dedicated route handler to bypass Next.js rewrite timeout (~30s limit).
     * 
     * @see https://ai.google.dev/gemini-api/docs/image-understanding#segmentation
     */
    async geminiImageSegment(request: {
        /** URL of the image to segment */
        image_url: string;
        /** Segmentation prompt (e.g., 'Segment all wooden and glass items') */
        prompt?: string;
        /** Model: gemini-2.5-flash, gemini-2.5-pro (ONLY 2.5+ models support segmentation) */
        model?: string;
        /** Media resolution: low, medium, high, ultra_high */
        media_resolution?: string;
    }) {
        const response = await this.client.post('/gemini/image-segment', request);
        return response.data;
    }

    /**
     * Analyze multiple images in a single request.
     * 
     * @description Compare, find differences, or analyze image sequences.
     * Limit: Up to 3600 images per request.
     * 
     * @see https://ai.google.dev/gemini-api/docs/image-understanding#prompting-with-multiple-images
     */
    async geminiImageUnderstandMulti(request: {
        /** List of image URLs to analyze */
        image_urls: string[];
        /** Analysis prompt for comparing/analyzing multiple images */
        prompt?: string;
        /** Model: gemini-3-flash-preview, gemini-3-pro-preview */
        model?: string;
        /** Media resolution: low, medium, high, ultra_high */
        media_resolution?: string;
    }) {
        const response = await this.client.post('/gemini/image-understand-multi', request);
        return response.data;
    }

    /**
     * Convert text to speech with 30+ voices and emotion control.
     * 
     * @description High-quality text-to-speech using Gemini's TTS models.
     * Supports expressive speech with Director's Notes for emotion/style control.
     * 
     * Models: gemini-2.5-flash-preview-tts, gemini-2.5-pro-preview-tts
     * 
     * Voices (30 total):
     * - Professional: Zephyr, Charon, Fenrir, Leda, Orus, Aoede, Callirrhoe, Autonoe
     * - Expressive: Puck, Kore, Perseus, Iapetus, Umbriel, Algieba, Despina, Erinome
     * - Casual: Achernar, Gacrux, Pulcherrima, Vindemiatrix, Sadachbia, Sadaltager
     * - Special: Sulafat, Laomedeia, Zubenelgenubi, Zubeneschamali, Schedar, Elara, Enceladus, Alnilam
     * 
     * @see https://ai.google.dev/gemini-api/docs/speech-generation
     */
    async geminiTTS(request: { 
        /** Text to convert to speech (supports SSML-like Director's Notes) */
        text: string; 
        /** Voice name (e.g., 'Puck', 'Charon', 'Kore') */
        voice_name?: string;
        /** Style prompt for emotion (e.g., 'cheerful', 'serious', 'whisper') */
        style_prompt?: string;
        /** Advanced voice configuration */
        voice_config?: any;
    }) {
        const response = await this.client.post('/gemini/tts', request);
        return response.data;
    }

    /**
     * Generate multi-speaker dialogue audio.
     * 
     * @description Creates audio with multiple distinct voices for conversations,
     * podcasts, or dramatic readings. Maximum 2 speakers per request.
     * 
     * **Text Format:**
     * ```
     * Speaker1: Hello, how are you?
     * Speaker2: I'm doing well, thanks for asking!
     * Speaker1: That's great to hear!
     * ```
     * 
     * **Important:** Speaker names in text must exactly match the 'name' field in speakers config.
     * 
     * **Style Control:**
     * ```
     * Make Speaker1 sound tired and bored, and Speaker2 sound excited and happy:
     * Speaker1: So... what's on the agenda today?
     * Speaker2: You're never going to guess!
     * ```
     * 
     * @see https://ai.google.dev/gemini-api/docs/speech-generation#multi-speaker
     */
    async geminiTTSMulti(request: {
        /** Script with speaker labels (format: 'Speaker1: text\nSpeaker2: text') */
        text: string;
        /** Speaker configurations with voice assignments (max 2) */
        speakers: { name: string; voice_name?: string }[];
        /** Model: gemini-2.5-flash-preview-tts or gemini-2.5-pro-preview-tts */
        model?: string;
    }) {
        const response = await this.client.post('/gemini/tts-multi', request);
        return response.data;
    }

    /**
     * Transcribe audio with speaker diarization and emotion detection.
     * 
     * @description Converts speech to text with structured output including:
     * - Summary of entire audio
     * - Segments with speaker diarization
     * - Timestamps in MM:SS format
     * - Language detection and translation
     * - Emotion detection (happy, sad, angry, neutral)
     * - Non-speech understanding (music, sirens, birdsong)
     * 
     * **Supported Formats:** WAV, MP3, AIFF, AAC, OGG, FLAC
     * **Max Duration:** 9.5 hours per prompt
     * **Token Rate:** 32 tokens per second of audio
     * **Resolution:** Downsampled to 16 Kbps, multi-channel → mono
     * 
     * **Structured Output Schema:**
     * ```json
     * {
     *   "summary": "Brief summary",
     *   "language": "Detected language",
     *   "segments": [{
     *     "speaker": "Speaker 1",
     *     "start_time": "00:00",
     *     "end_time": "00:15",
     *     "text": "Transcribed text",
     *     "emotion": "happy"
     *   }]
     * }
     * ```
     * 
     * @see https://ai.google.dev/gemini-api/docs/audio
     */
    async geminiAudioTranscribe(request: {
        /** URL to audio file (MP3, WAV, etc.) */
        audio_url?: string;
        /** YouTube video URL (extracts and transcribes audio) */
        youtube_url?: string;
        /** Base64-encoded audio data (for microphone recordings) */
        audio_base64?: string;
        /** Include MM:SS timestamps for each segment */
        include_timestamps?: boolean;
        /** Enable speaker diarization (identify different speakers) */
        include_speaker_labels?: boolean;
        /** Detect speaker emotion (happy, sad, angry, neutral) */
        detect_emotion?: boolean;
        /** Detect the spoken language */
        detect_language?: boolean;
        /** Translate non-English segments to English */
        translate_to_english?: boolean;
        /** Expected number of speakers (for diarization) */
        num_speakers?: number;
        /** Language hint (e.g., 'en', 'es', 'ja') */
        language?: string;
        /** Start timestamp MM:SS for segment extraction */
        start_time?: string;
        /** End timestamp MM:SS for segment extraction */
        end_time?: string;
        /** Custom prompt for specialized transcription */
        prompt?: string;
    }) {
        // Extended timeout for YouTube download + transcription (can take 60-180s)
        const response = await this.client.post('/gemini/audio-transcribe', request, {
            timeout: 180000, // 3 minutes
        });
        return response.data;
    }

    /**
     * Generate vector embeddings for semantic search and similarity.
     * 
     * @description Creates numerical vector representations of text for:
     * - Semantic search (find by meaning, not keywords)
     * - Document clustering
     * - Text classification
     * - RAG (Retrieval Augmented Generation)
     * 
     * Model: gemini-embedding-001 (free tier)
     * Max tokens: 2048
     * Dimensions: 768, 1536, or 3072 (default)
     * 
     * @see https://ai.google.dev/gemini-api/docs/embeddings
     */
    async geminiEmbeddings(request: { 
        /** Text to embed */
        content: string; 
        /** Task type: SEMANTIC_SIMILARITY, RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY, CLASSIFICATION, CLUSTERING, CODE_RETRIEVAL_QUERY, QUESTION_ANSWERING, FACT_VERIFICATION */
        task_type?: string; 
        /** Vector dimensions: 768 (fast), 1536 (balanced), 3072 (highest quality) */
        output_dimensionality?: number 
    }) {
        const response = await this.client.post('/gemini/embeddings', request);
        return response.data;
    }

    /**
     * Ground responses with web page content.
     * 
     * @description Fetches and processes web pages to provide context for responses.
     * Can combine with Google Search for comprehensive grounding.
     */
    async geminiURLContext(request: { 
        /** URLs to fetch and use as context (1-20) */
        urls: string[];
        /** Question or instruction about the content */
        prompt: string;
        /** Model to use */
        model?: string;
        /** System instruction to guide response style */
        system_instruction?: string;
        /** Also include Google Search results */
        combine_with_search?: boolean;
        /** Include source citations in response */
        include_citations?: boolean;
        /** Dynamic retrieval threshold (0.0-1.0, lower = more retrieval) */
        dynamic_retrieval_threshold?: number;
    }) {
        const response = await this.client.post('/gemini/url-context', request);
        return response.data;
    }

    /**
     * List all predefined function calling scenarios.
     * 
     * @description Returns available scenarios with their functions and example prompts.
     * Each scenario demonstrates different function calling patterns:
     * - weather: Basic function calling
     * - smart_home: Parallel function calling (multiple functions at once)
     * - calendar: Compositional/sequential calling
     * - ecommerce: Complex multi-step workflows
     * - database: Data manipulation patterns
     * - api_workflow: External API integration
     * 
     * @see https://ai.google.dev/gemini-api/docs/function-calling
     */
    async geminiFunctionCallingScenarios() {
        const response = await this.client.get('/gemini/function-calling/scenarios');
        return response.data;
    }

    /**
     * Get details of a specific function calling scenario.
     * 
     * @description Returns full function declarations and example prompts for a scenario.
     */
    async geminiFunctionCallingScenario(scenarioId: string) {
        const response = await this.client.get(`/gemini/function-calling/scenarios/${scenarioId}`);
        return response.data;
    }

    /**
     * Simulate function execution with mock data.
     * 
     * @description Executes a function with realistic mock results for demos.
     * Useful for testing without real integrations.
     */
    async geminiFunctionSimulate(functionName: string, args: Record<string, any>) {
        const response = await this.client.post(`/gemini/function-calling/simulate?function_name=${functionName}`, args);
        return response.data;
    }

    /**
     * Comprehensive function calling with all features.
     * 
     * @description Enables the model to call predefined functions to get data
     * or perform actions. Supports all function calling patterns:
     * 
     * **Modes:**
     * - AUTO: Model decides when to call functions (default)
     * - ANY: Force function call, optionally restricted to specific functions
     * - NONE: Disable function calling (functions as context only)
     * - VALIDATED: Like ANY but allows text responses when appropriate
     * 
     * **Features:**
     * - Parallel function calling (multiple functions in one turn)
     * - Compositional calling (chained function workflows)
     * - Multi-tool use (combine with Google Search, Code Execution)
     * - Multi-turn conversation support
     * - Automatic simulation for demos
     * - 6 predefined scenarios with 25+ functions
     * 
     * @example
     * ```typescript
     * // Basic usage with predefined scenario
     * const result = await apiClient.geminiFunctionCalling({
     *   prompt: "What's the weather in Tokyo?",
     *   scenario: "weather"
     * });
     * 
     * // Parallel calling with smart home
     * const result = await apiClient.geminiFunctionCalling({
     *   prompt: "Turn on lights, set thermostat to 72, and play jazz",
     *   scenario: "smart_home",
     *   simulate_execution: true
     * });
     * 
     * // Custom functions with mode restriction
     * const result = await apiClient.geminiFunctionCalling({
     *   prompt: "Get user data",
     *   mode: "ANY",
     *   allowed_function_names: ["query_users"],
     *   functions: [{ name: "query_users", ... }]
     * });
     * ```
     * 
     * @see https://ai.google.dev/gemini-api/docs/function-calling
     */
    async geminiFunctionCalling(request: { 
        /** The prompt/query */
        prompt: string;
        /** Model to use */
        model?: string;
        /** Function calling mode: AUTO, ANY, NONE, VALIDATED */
        mode?: 'AUTO' | 'ANY' | 'NONE' | 'VALIDATED';
        /** Restrict to specific functions by name (for ANY/VALIDATED modes) */
        allowed_function_names?: string[];
        /** Custom function declarations */
        functions?: Array<{
            name: string;
            description: string;
            parameters: Record<string, any>;
        }>;
        /** Use predefined scenario: weather, smart_home, calendar, ecommerce, database, api_workflow */
        scenario?: string;
        /** Results from previous function calls for multi-turn */
        function_results?: Array<{
            name: string;
            result: Record<string, any>;
        }>;
        /** Full conversation history for complex multi-turn */
        conversation_history?: Array<{
            role: 'user' | 'model' | 'function';
            content?: string;
            function_call?: { name: string; args: Record<string, any> };
            function_response?: { name: string; result: Record<string, any> };
        }>;
        /** Enable Google Search alongside function calling */
        enable_google_search?: boolean;
        /** Enable Code Execution alongside function calling */
        enable_code_execution?: boolean;
        /** Automatically execute functions with mock data (for demos) */
        simulate_execution?: boolean;
        /** Temperature (0.0 recommended for function calling) */
        temperature?: number;
        /** Maximum tokens in response */
        max_tokens?: number;
    }) {
        const response = await this.client.post('/gemini/function-calling', request);
        return response.data;
    }

    // =========================================================================
    // FILE SEARCH (RAG) API
    // =========================================================================

    /**
     * Create a semantic file search store.
     * 
     * @description Creates a vector store for semantic search across documents.
     * Documents are automatically chunked and embedded for efficient retrieval.
     * 
     * @see https://ai.google.dev/gemini-api/docs/file-search
     */
    async geminiFileSearchStore(request: {
        /** Unique name for the store */
        name: string;
        /** Human-readable display name */
        display_name?: string;
        /** Description of the store */
        description?: string;
    }) {
        const response = await this.client.post('/gemini/file-search-store', request);
        return response.data;
    }

    /**
     * Upload content to a file search store.
     * 
     * @description Uploads and indexes content for semantic search.
     * Supports custom chunking configuration and metadata for filtering.
     */
    async geminiFileSearchUpload(request: {
        /** Name of the target store */
        store_name: string;
        /** Text content to upload */
        content: string;
        /** Display name for the document */
        display_name?: string;
        /** Custom metadata for filtering (array of {key, string_value?, numeric_value?}) */
        custom_metadata?: Array<{
            key: string;
            string_value?: string;
            numeric_value?: number;
        }>;
        /** Chunking configuration */
        chunking_config?: {
            /** Max tokens per chunk (100-2000, default: 1024) */
            max_tokens_per_chunk?: number;
            /** Overlap between chunks (0-200, default: 100) */
            max_overlap_tokens?: number;
        };
    }) {
        const response = await this.client.post('/gemini/file-search-upload', request);
        return response.data;
    }

    /**
     * Query file search stores with semantic search.
     * 
     * @description Performs semantic search across indexed documents.
     * Supports metadata filtering, structured output, and citations.
     */
    async geminiFileSearchQuery(request: {
        /** Name(s) of the store(s) to search (comma-separated for multiple) */
        store_names: string[] | string;
        /** Search query (natural language) */
        query: string;
        /** Model to use (default: gemini-2.5-flash) */
        model?: string;
        /** Metadata filter for results */
        metadata_filter?: Record<string, string | number>;
        /** JSON schema for structured output */
        response_schema?: Record<string, unknown>;
        /** Include source citations in response */
        include_citations?: boolean;
    }) {
        const response = await this.client.post('/gemini/file-search-query', request);
        return response.data;
    }

    /**
     * List all file search stores.
     */
    async geminiFileSearchList() {
        const response = await this.client.get('/gemini/file-search-stores');
        return response.data;
    }

    /**
     * Get details about a specific store.
     */
    async geminiFileSearchGetStore(storeName: string) {
        const response = await this.client.get(`/gemini/file-search-stores/${encodeURIComponent(storeName)}`);
        return response.data;
    }

    /**
     * Delete a file search store.
     * 
     * @description Permanently removes a store and all its indexed content.
     */
    async geminiFileSearchDeleteStore(storeName: string, force: boolean = false) {
        const response = await this.client.delete(`/gemini/file-search-stores/${encodeURIComponent(storeName)}?force=${force}`);
        return response.data;
    }

    /**
     * List documents in a file search store.
     */
    async geminiFileSearchDocuments(storeName: string) {
        const response = await this.client.get(`/gemini/file-search-documents/${encodeURIComponent(storeName)}`);
        return response.data;
    }

    /**
     * Delete a document from a file search store.
     */
    async geminiFileSearchDeleteDocument(documentName: string) {
        const response = await this.client.delete(`/gemini/file-search-documents/${encodeURIComponent(documentName)}`);
        return response.data;
    }

    // =========================================================================
    // CONTEXT CACHING API
    // =========================================================================

    /**
     * Get context caching info and capabilities.
     * 
     * @description Returns information about implicit vs explicit caching,
     * model requirements, and pricing details.
     */
    async geminiCacheInfo() {
        const response = await this.client.get('/gemini/cache-info');
        return response.data;
    }

    /**
     * Create a cached context for repeated queries.
     * 
     * @description Caches large content (documents, system prompts, context) for reuse.
     * Reduces costs by 75% for cached tokens.
     * 
     * Minimum tokens for caching:
     * - Gemini 2.5 Flash: 1,024 tokens (~4,096 chars)
     * - Gemini 2.5 Pro: 4,096 tokens (~16,384 chars)
     * 
     * @see https://ai.google.dev/gemini-api/docs/caching
     */
    async geminiCacheCreate(request: {
        /** Unique name for the cache */
        name?: string;
        /** Human-readable display name */
        display_name?: string;
        /** Text content to cache (required if not using file_uri) */
        content?: string;
        /** File URI to cache (from File API, for video/PDF/audio) */
        file_uri?: string;
        /** MIME type of the file (e.g., 'video/mp4', 'application/pdf') */
        file_mime_type?: string;
        /** System instruction to cache */
        system_instruction?: string;
        /** Time to live in seconds (e.g., 3600 for 1 hour) */
        ttl_seconds?: number;
        /** Explicit expiration time (ISO 8601 format) */
        expire_time?: string;
        /** Model to use (default: gemini-2.5-flash-001) */
        model?: string;
    }) {
        const response = await this.client.post('/gemini/cache-create', request);
        return response.data;
    }

    /**
     * Query using cached context.
     * 
     * @description Sends a query using a previously cached context.
     * Response includes cache_info showing cached token usage.
     */
    async geminiCacheQuery(request: {
        /** Name/ID of the cache to use */
        cache_name: string;
        /** Query to run against the cached context */
        prompt: string;
        /** Temperature (0.0-2.0, default: 1.0) */
        temperature?: number;
    }) {
        const response = await this.client.post('/gemini/cache-query', request);
        return response.data;
    }

    /**
     * List all active context caches.
     * 
     * @description Returns all caches that haven't expired.
     */
    async geminiCacheList() {
        const response = await this.client.get('/gemini/cache-list');
        return response.data;
    }

    /**
     * Get details about a specific cache.
     */
    async geminiCacheGet(cacheName: string) {
        const response = await this.client.get(`/gemini/cache-get/${encodeURIComponent(cacheName)}`);
        return response.data;
    }

    /**
     * Update cache TTL or expiration time.
     * 
     * @description Extends or shortens the lifetime of a cache.
     */
    async geminiCacheUpdate(request: {
        /** Name/ID of the cache to update */
        cache_name: string;
        /** New TTL in seconds */
        ttl_seconds?: number;
        /** Explicit expiration timestamp (ISO 8601) */
        expire_time?: string;
    }) {
        const response = await this.client.post('/gemini/cache-update', request);
        return response.data;
    }

    /**
     * Delete a context cache.
     * 
     * @description Immediately removes a cache and frees resources.
     */
    async geminiCacheDelete(cacheName: string) {
        const response = await this.client.delete(`/gemini/cache-delete/${encodeURIComponent(cacheName)}`);
        return response.data;
    }
    // *** END DEMO CODE ***


    // Health check
    async healthCheck() {
        const response = await this.client.get('/health');
        return response.data;
    }

    // ── Setup wizard (public — uses X-Setup-Key, no Discord auth) ────────────

    /** Check whether the platform is in wizard (unconfigured) mode. */
    async getSetupState() {
        const response = await this.client.get('/setup/state');
        return response.data;
    }

    // ── System Configuration (Level 5) ──────────────────────────────────────

    /** List all application settings with metadata and current values. */
    async getConfigSettings() {
        const response = await this.client.get('/config/settings');
        return response.data;
    }

    /** List database connection settings (PostgreSQL + Redis). */
    async getDatabaseSettings() {
        const response = await this.client.get('/config/settings/database');
        return response.data;
    }

    /** Bulk-update one or more settings. Dynamic settings apply immediately. */
    async updateConfigSettings(settings: Array<{ key: string; value: string }>) {
        const response = await this.client.put('/config/settings', { settings });
        return response.data;
    }

    /** Re-publish all dynamic DB overrides to Redis (use after Redis restart). */
    async refreshDynamicSettings() {
        const response = await this.client.post('/config/settings/refresh');
        return response.data;
    }

    /** Remove a database override for a setting key, reverting to env default. */
    async deleteConfigOverride(key: string) {
        const response = await this.client.delete(`/config/settings/${encodeURIComponent(key)}`);
        return response.data;
    }

    /** Get LLM provider API key status from the encrypted settings file. */
    async getApiKeys() {
        const response = await this.client.get('/config/api-keys');
        return response.data as Record<string, { friendly_name: string; description: string; is_set: boolean; masked_value: string | null }>;
    }

    /** Update one or more LLM provider API keys in the encrypted settings file. */
    async updateApiKeys(settings: Record<string, string>, encryptionKey: string) {
        const response = await this.client.put('/config/api-keys', { settings }, { headers: { 'X-Setup-Key': encryptionKey } });
        return response.data as { updated: string[]; cleared: string[]; restart_recommended: boolean; message: string };
    }

    // ── Database Management (Level 5) ────────────────────────────────────────

    /** Get framework version, DB schema version, and connection status. */
    async getDatabaseInfo() {
        const response = await this.client.get('/database/info');
        return response.data;
    }

    /** List Alembic migration history and current revision. */
    async getDatabaseMigrations() {
        const response = await this.client.get('/database/migrations');
        return response.data;
    }

    /** Run `alembic upgrade head` to apply all pending migrations. */
    async applyDatabaseMigrations() {
        const response = await this.client.post('/database/migrations/upgrade');
        return response.data;
    }

    /** Apply only pending framework migrations (up to REQUIRED_DB_REVISION). Plugin branches are unaffected. */
    async upgradeFrameworkSchema() {
        const response = await this.client.post('/database/migrations/framework/upgrade');
        return response.data;
    }

    /** Apply the migration for a specific plugin (independent Alembic branch). */
    async applyPluginMigration(pluginName: string) {
        const response = await this.client.post(`/database/migrations/plugins/${pluginName}/apply`);
        return response.data;
    }

    /** Test that the currently configured PostgreSQL and Redis connections are healthy. */
    async testDatabaseConnection() {
        const response = await this.client.post('/database/test-connection');
        return response.data;
    }

    /** Run the full database validation suite (tables, columns, schema version, seeded data). */
    async validateDatabase() {
        const response = await this.client.get('/database/validate');
        return response.data;
    }

    // ── Bot Identity (public) ────────────────────────────────────────────────

    /** Fetch public bot identity (name, tagline, description, logo, invite URL). No auth required. */
    async getBotPublicInfo() {
        const response = await this.client.get('/bot-info/public');
        return response.data;
    }

    // ── Instrumentation ──────────────────────────────────────────────────────

    /**
     * Record a dashboard card click.
     * Fire-and-forget — errors are silently swallowed so tracking never blocks navigation.
     */
    trackCardClick(cardId: string, guildId?: string | null): void {
        this.client.post('/instrumentation/card-click', {
            card_id: cardId,
            guild_id: guildId ? parseInt(guildId) : null,
        }).catch(() => { /* non-critical */ });
    }

    /**
     * Fetch aggregated instrumentation stats for the developer dashboard.
     * range: "24h" | "7d" | "30d"
     */
    async getInstrumentationStats(range: '24h' | '7d' | '30d' = '7d', guildId?: string | null) {
        const params: Record<string, string> = { range };
        if (guildId) params.guild_id = guildId;
        const response = await this.client.get('/instrumentation/stats', { params });
        return response.data;
    }

    async purgeInstrumentationData(params: { older_than_days?: number; before?: string; after?: string; tables?: string }) {
        const response = await this.client.delete('/instrumentation/data', { params });
        return response.data as { deleted: Record<string, number> };
    }

    // ── LLM Schema Store ──────────────────────────────────────────────────

    async listLlmSchemas() {
        const response = await this.client.get('/gemini/schemas');
        return response.data;
    }

    async getLlmSchema(schemaId: string) {
        const response = await this.client.get(`/gemini/schemas/${schemaId}`);
        return response.data;
    }

    async upsertLlmSchema(schemaId: string, body: Record<string, any>) {
        const response = await this.client.post(`/gemini/schemas/${schemaId}`, body);
        return response.data;
    }

    async deleteLlmSchema(schemaId: string) {
        const response = await this.client.delete(`/gemini/schemas/${schemaId}`);
        return response.data;
    }

    // ── LLM Function Set Store ────────────────────────────────────────────

    async listLlmFunctionSets() {
        const response = await this.client.get('/gemini/function-sets');
        return response.data;
    }

    async getLlmFunctionSet(setId: string) {
        const response = await this.client.get(`/gemini/function-sets/${setId}`);
        return response.data;
    }

    async upsertLlmFunctionSet(setId: string, body: Record<string, any>) {
        const response = await this.client.post(`/gemini/function-sets/${setId}`, body);
        return response.data;
    }

    async deleteLlmFunctionSet(setId: string) {
        const response = await this.client.delete(`/gemini/function-sets/${setId}`);
        return response.data;
    }

    // ── LLM Call Logs ─────────────────────────────────────────────────────

    async getLlmLogs(params: { limit?: number; offset?: number; model?: string; endpoint?: string } = {}) {
        const response = await this.client.get('/gemini/logs', { params });
        return response.data;
    }

    // ── Plugin Prompt Files ───────────────────────────────────────────────
    // Layout: /data/prompts/{plugin}/{context}/{file}.txt — DEVELOPER only
    //
    // Each "context" is a purpose folder chosen by the plugin (e.g. "ticket_intake",
    // "faq_answers"). Within each context there are named files: "system_prompt",
    // "user_prompt", etc.

    async listPluginPrompts(): Promise<{ plugins: Array<{ plugin_name: string; display_name: string; contexts: any[] }> }> {
        const response = await this.client.get('/prompts/');
        return response.data;
    }

    async getPromptFile(pluginName: string, context: string, fileName: string): Promise<{ plugin_name: string; context_name: string; name: string; label: string; description: string; content: string }> {
        const response = await this.client.get(`/prompts/${pluginName}/${context}/${fileName}`);
        return response.data;
    }

    async savePromptFile(pluginName: string, context: string, fileName: string, content: string): Promise<{ ok: boolean }> {
        const response = await this.client.put(`/prompts/${pluginName}/${context}/${fileName}`, { content });
        return response.data;
    }

    async resetPromptFile(pluginName: string, context: string, fileName: string): Promise<{ ok: boolean; content: string }> {
        const response = await this.client.post(`/prompts/${pluginName}/${context}/${fileName}/reset`);
        return response.data;
    }

    // ── Generic LLM (multi-provider) ──────────────────────────────────────

    async llmGenerate(prompt: string, options: { system_prompt?: string; provider?: string; model?: string; guild_id?: number } = {}) {
        const response = await this.client.post('/llm/generate', { prompt, ...options });
        return response.data as { content: string };
    }

    async llmStructured(prompt: string, schema_name: string, options: { provider?: string; model?: string; guild_id?: number } = {}) {
        const response = await this.client.post('/llm/structured', { prompt, schema_name, ...options });
        return response.data;
    }

    async llmTools(prompt: string, scenario: string, options: { provider?: string; model?: string; guild_id?: number } = {}) {
        const response = await this.client.post('/llm/tools', { prompt, scenario, ...options });
        return response.data;
    }

    // ── Commands ───────────────────────────────────────────────────────────

    async getCommands(): Promise<{ commands: any[]; last_updated: string | null; total: number }> {
        const response = await this.client.get('/commands');
        return response.data;
    }

    async refreshCommands(): Promise<void> {
        await this.client.post('/commands/refresh');
    }

    async getSettingsSchema(): Promise<{ schemas: SettingsSchema[] }> {
        const response = await this.client.get('/bot-info/settings-schema');
        return response.data;
    }

    // ── Card Visibility ────────────────────────────────────────────────────

    async getCardVisibility(guildId: string): Promise<Record<string, boolean>> {
        const response = await this.client.get(`/guilds/${guildId}/card-visibility`);
        return response.data.visibility ?? {};
    }

    async updateCardVisibility(guildId: string, visibility: Record<string, boolean>): Promise<void> {
        await this.client.put(`/guilds/${guildId}/card-visibility`, { visibility });
    }

    // ── Generic helpers ────────────────────────────────────────────────────
    // Use these in plugin pages — do NOT add named methods to this file.

    async get<T = unknown>(path: string, params?: Record<string, unknown>): Promise<T> {
        const response = await this.client.get(path, { params });
        return response.data as T;
    }

    async post<T = unknown>(path: string, data?: unknown): Promise<T> {
        const response = await this.client.post(path, data);
        return response.data as T;
    }

    async put<T = unknown>(path: string, data?: unknown): Promise<T> {
        const response = await this.client.put(path, data);
        return response.data as T;
    }

    async delete<T = unknown>(path: string): Promise<T> {
        const response = await this.client.delete(path);
        return response.data as T;
    }
}

export const apiClient = new APIClient();
