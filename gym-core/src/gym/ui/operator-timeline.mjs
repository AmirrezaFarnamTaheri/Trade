export async function loadTimeline(request, source) {
  const query = new URLSearchParams({limit: "50"});
  if (source) query.set("source", source);
  const response = await request("/api/timeline?" + query);
  return {
    events: Array.isArray(response.events) ? response.events : [],
    unavailable: Object.entries(response.sources || {}).filter(([, status]) => typeof status === "string"),
  };
}
