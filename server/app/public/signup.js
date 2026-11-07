const form = document.getElementById("signup");
const status = document.getElementById("status");
const submit = document.getElementById("submit");

async function load() {
  try {
    const response = await fetch("/api/public/subscription-options");
    if (!response.ok) throw new Error("Unable to load agencies. Please try again later.");
    const options = await response.json();
    const agency = document.getElementById("agency");
    agency.replaceChildren(new Option("Choose an agency", ""));
    for (const item of options.agencies) agency.add(new Option(item.name, item.id));
    agency.disabled = false;
    document.getElementById("count").max = options.max_digest_grants;
    document.getElementById("award").min = options.financial_floor;
    document.getElementById("award").value = options.financial_floor;
    submit.disabled = false;
  } catch (error) { status.textContent = error.message; }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submit.disabled) return;
  submit.disabled = true;
  status.textContent = "Requesting confirmation…";
  const values = new FormData(form);
  try {
    const response = await fetch("/api/public/subscriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: values.get("email"), agency_id: values.get("agency_id"),
        frequency: values.get("frequency"), top_n: Number(values.get("top_n")),
        website: values.get("website"),
        filters: { min_score: Number(values.get("min_score")), min_award: Number(values.get("min_award")), q: values.get("q") },
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      const retry = response.headers.get("Retry-After");
      throw new Error(response.status === 429
        ? `${typeof data.detail === "string" ? data.detail : "Too many requests."} Try again in ${retry || 60} seconds.`
        : typeof data.detail === "string" ? data.detail : "Check your settings and try again.");
    }
    status.textContent = data.message;
  } catch (error) { status.textContent = error.message; }
  finally { submit.disabled = false; }
});
load();
