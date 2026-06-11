// Liveness endpoint for the container healthcheck (docker-compose curls /api/health).
// Kept trivial and dependency-free so it reflects only that the Next server is up.
export const dynamic = 'force-dynamic';

export function GET() {
    return Response.json({ status: 'ok' });
}
