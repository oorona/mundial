export async function register() {
    if (process.env.NEXT_RUNTIME === 'nodejs') {
        const { v4: uuidv4 } = await import('uuid');
        // We can't use standard Interval here easily because register runs in a specific context
        // But in recent Next.js, we can just start a timer.

        const INSTANCE_ID = uuidv4().slice(0, 8); // Short ID
        const START_TIME = Date.now();
        // Use INTERNAL_API_URL for docker networking, fall back to localhost if running locally
        const API_URL = process.env.INTERNAL_API_URL || 'http://localhost:8000';

        console.log(`[Frontend] Starting Frontend Instance: ${INSTANCE_ID}`);

        // Simple Heartbeat Loop
        setInterval(async () => {
            try {
                const uptime = (Date.now() - START_TIME) / 1000;
                await fetch(`${API_URL}/api/v1/platform/heartbeat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: INSTANCE_ID,
                        uptime: uptime,
                        timestamp: Date.now() / 1000
                    })
                });
            } catch (err) {
                // Silent fail to not spam logs if backend is down
                // console.error('[Frontend] Heartbeat failed:', err);
            }
        }, 10000); // 10s interval
    }
}
