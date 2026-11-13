export function GET() {
  return Response.json({
    status: 'ok',
    service: 'lunar-landing-site-navigator',
    ephemerisProvider: 'not-configured',
  });
}
