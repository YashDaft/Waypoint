/*
 * Waypoint frontend
 *
 * Flow: Plan my trip -> guardrail + supervisor + specialist agents
 *       -> review the draft -> approve or revise -> final plan
 */

let currentThreadId = null;   // thread of the plan currently on screen
let latestAnswerMarkdown = "";
let latestStage = "final";    // "draft" or "final"
let waitingForApproval = false;
let timerId = null;           // the elapsed-time counter while a request runs

// The supervisor returns agent ids. "source" names where the agent gets its
// live data from; agents without a source only reason over that data.
// "output" is the field in the API response that holds what the agent found.
const AGENT_META = {
    flight_agent: { label: "✈️ Flights", source: "Live Google Flights fares (custom MCP)", output: "flight_results" },
    hotel_agent: { label: "🏨 Hotels", source: "Tavily web search (MCP)", output: "hotel_results" },
    weather_agent: { label: "🌦️ Weather", source: "OpenWeather (custom MCP)", output: "weather_results" },
    budget_agent: { label: "💰 Budget", output: "budget_results" },
    itinerary_agent: { label: "🗓️ Itinerary" }
};

function $(id) {
    return document.getElementById(id);
}

function scrollToElement(element, block = "start") {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    element.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: block });
}

function setPrompt(text) {
    const input = $("userInput");
    input.value = text;
    input.focus();
}

/* ---------- server status ---------- */

// Asks the backend's /health route whether it is up, so the pill shows the real state.
async function checkHealth() {
    const pill = $("statusPill");
    const label = $("statusText");

    try {
        const response = await fetch("/health");
        const isOnline = response.ok;

        pill.className = isOnline ? "status-pill online" : "status-pill offline";
        label.textContent = isOnline ? "Online" : "Offline";
    } catch (error) {
        pill.className = "status-pill offline";
        label.textContent = "Offline";
    }
}

/* ---------- loading states ---------- */

// Shows how long the current request has been running, for example 0:42.
function startTimer(onTick) {
    const startedAt = Date.now();

    stopTimer();
    onTick("0:00");

    timerId = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        const minutes = Math.floor(seconds / 60);
        const rest = String(seconds % 60).padStart(2, "0");
        onTick(`${minutes}:${rest}`);
    }, 1000);
}

function stopTimer() {
    if (timerId) {
        clearInterval(timerId);
        timerId = null;
    }
}

function setLoading(isLoading) {
    $("sendBtn").disabled = isLoading;
    $("btnText").classList.toggle("hidden", isLoading);
    $("btnLoader").classList.toggle("hidden", !isLoading);
    $("loadingNote").classList.toggle("hidden", !isLoading);

    if (isLoading) {
        startTimer((time) => {
            $("loadingTimer").textContent = time;
        });
    } else {
        stopTimer();
    }
}

function setApprovalLoading(isLoading, approved = true) {
    const approveBtn = $("approveBtn");
    const reviseBtn = $("reviseBtn");
    const discardBtn = $("discardBtn");

    // Remember the original labels so they can be restored afterwards.
    [approveBtn, reviseBtn].forEach((button) => {
        if (!button.dataset.label) {
            button.dataset.label = button.textContent.trim();
        }
    });

    $("sendBtn").disabled = isLoading;
    approveBtn.disabled = isLoading;
    reviseBtn.disabled = isLoading;
    discardBtn.disabled = isLoading;

    if (isLoading) {
        const button = approved ? approveBtn : reviseBtn;
        const text = approved ? "Writing final plan" : "Applying your changes";

        startTimer((time) => {
            button.textContent = `${text} ${time}`;
        });
    } else {
        stopTimer();
        approveBtn.textContent = approveBtn.dataset.label;
        reviseBtn.textContent = reviseBtn.dataset.label;
    }
}

/* ---------- errors ---------- */

function showError(message) {
    const errorBox = $("errorBox");
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
    scrollToElement(errorBox, "center");
}

function hideError() {
    const errorBox = $("errorBox");
    errorBox.classList.add("hidden");
    errorBox.textContent = "";
}

/* ---------- rendering ---------- */

// Turns markdown into HTML. DOMPurify removes anything unsafe first, because the
// text comes from an AI model and from web search results.
function renderMarkdown(element, markdown) {
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
        // images are blocked too: a plan never needs them, and web content could add tracking pixels
        element.innerHTML = DOMPurify.sanitize(marked.parse(markdown || ""), { FORBID_TAGS: ["img"] });
    } else {
        element.textContent = markdown || "";
    }
}

// "2026-12-20" -> "20 Dec 2026". Anything else is shown as it is.
function formatDate(text) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text || "")) {
        return text || "";
    }

    const [year, month, day] = text.split("-").map(Number);
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${day} ${months[month - 1]} ${year}`;
}

// One labelled value on the trip card, for example "Leaving" / "20 Dec 2026".
function tripDetail(label, value) {
    const item = document.createElement("div");
    item.className = "trip-detail";

    const name = document.createElement("span");
    name.className = "trip-detail-label";
    name.textContent = label;

    const text = document.createElement("span");
    text.className = "trip-detail-value";
    text.textContent = value;

    item.append(name, text);
    return item;
}

// One end of the route on the trip card: the airport code big, the city small.
function tripPlace(code, city, fallback) {
    const place = document.createElement("div");
    place.className = "trip-place";

    const codeText = document.createElement("span");
    codeText.className = "trip-code";
    codeText.textContent = code || "···";

    const cityText = document.createElement("span");
    cityText.className = "trip-city";
    cityText.textContent = city || fallback;

    place.append(codeText, cityText);
    return place;
}

// Shows what the supervisor understood about the trip, like a boarding pass.
function showTripCard(constraints) {
    const card = $("tripCard");
    const trip = constraints || {};
    card.replaceChildren();

    // nothing useful to show if the supervisor found neither end of the trip
    if (!trip.destination && !trip.origin) {
        card.classList.add("hidden");
        return;
    }

    const route = document.createElement("div");
    route.className = "trip-route";

    const line = document.createElement("span");
    line.className = "trip-line";
    line.setAttribute("aria-hidden", "true");

    route.append(
        tripPlace(trip.origin_airport, trip.origin, "Origin not given"),
        line,
        tripPlace(trip.destination_airport, trip.destination, "Destination not given")
    );

    const details = document.createElement("div");
    details.className = "trip-details";

    details.append(tripDetail("Leaving", trip.travel_date ? formatDate(trip.travel_date) : "Flexible"));

    if (trip.trip_days) {
        const days = Number(trip.trip_days);
        details.append(tripDetail("Length", days === 1 ? "1 day" : `${trip.trip_days} days`));
    } else if (trip.duration) {
        details.append(tripDetail("Length", trip.duration));
    }

    if (trip.budget) {
        details.append(tripDetail("Budget", trip.budget));
    }

    card.append(route, details);
    card.classList.remove("hidden");
}

// Adds one step to the route. state is "done", "current" or "next".
function addRouteStop(route, label, source, state) {
    const stop = document.createElement("li");
    stop.className = `route-stop ${state}`;
    stop.style.setProperty("--i", route.children.length);

    const name = document.createElement("span");
    name.className = "route-stop-name";
    name.textContent = label;
    stop.appendChild(name);

    if (source) {
        const sourceText = document.createElement("span");
        sourceText.className = "route-stop-source";
        sourceText.textContent = source;
        stop.appendChild(sourceText);
    }

    route.appendChild(stop);
}

// The agents that ran, then the review and the final plan.
function showRoute(selectedAgents, stage) {
    const route = $("agentRoute");
    route.replaceChildren();

    selectedAgents.forEach((agent) => {
        const meta = AGENT_META[agent] || { label: agent };
        addRouteStop(route, meta.label, meta.source, "done");
    });

    if (stage === "draft") {
        addRouteStop(route, "👤 Your review", "Waiting for you", "current");
        addRouteStop(route, "✨ Final plan", "", "next");
    } else {
        addRouteStop(route, "👤 Your review", "Approved", "done");
        addRouteStop(route, "✨ Final plan", "Ready", "done");
    }
}

// A collapsible panel per specialist agent with what it returned.
function showAgentOutputs(data) {
    const list = $("agentOutputList");
    list.replaceChildren();

    (data.selected_agents || []).forEach((agent) => {
        const meta = AGENT_META[agent];
        const text = meta && meta.output ? data[meta.output] : "";

        if (!text || typeof text !== "string") {
            return;
        }

        const panel = document.createElement("details");
        panel.className = "agent-output";

        const summary = document.createElement("summary");
        summary.textContent = meta.label;

        const body = document.createElement("div");
        body.className = "agent-output-body";
        renderMarkdown(body, text);

        panel.append(summary, body);
        list.appendChild(panel);
    });

    $("agentOutputs").classList.toggle("hidden", list.children.length === 0);
}

function showWorkflow(data, stage) {
    const blocked = data.guardrail_allowed === false;
    const badge = $("guardrailBadge");

    $("workflowTitle").textContent = blocked ? "Request blocked" : "Your route";
    $("workflowSubtitle").textContent = blocked
        ? "The guardrail stopped this request before any agent ran."
        : "Chosen by the supervisor agent for your request.";

    $("supervisorReasoning").textContent = blocked
        ? (data.supervisor_reasoning || data.answer || "Waypoint only helps with travel planning.")
        : (data.supervisor_reasoning || "Supervisor routing completed.");

    badge.textContent = blocked ? "Guardrail blocked" : "Guardrail passed";
    badge.classList.toggle("blocked", blocked);

    if (blocked) {
        $("tripCard").classList.add("hidden");
        $("agentRoute").replaceChildren();
        $("agentOutputs").classList.add("hidden");
    } else {
        showTripCard(data.trip_constraints);
        showRoute(data.selected_agents || [], stage);
        showAgentOutputs(data);
    }

    $("workflowSection").classList.remove("hidden");
}

function showResult(markdown, threadId, stage) {
    latestAnswerMarkdown = markdown || "";
    latestStage = stage;

    renderMarkdown($("resultBox"), latestAnswerMarkdown);

    $("resultTitle").textContent = stage === "draft" ? "Your draft plan" : "Your final plan";
    $("stagePill").textContent = stage === "draft" ? "Draft" : "Final";
    $("stagePill").classList.toggle("final", stage !== "draft");
    $("resultHint").classList.toggle("hidden", stage !== "draft");
    $("newPlanRow").classList.toggle("hidden", stage === "draft");
    $("threadInfo").textContent = `Plan ID: ${threadId}`;

    const section = $("resultSection");
    section.classList.remove("hidden");
    scrollToElement(section);
}

function hideResult() {
    latestAnswerMarkdown = "";
    $("resultSection").classList.add("hidden");
}

function showApproval(data) {
    waitingForApproval = true;

    $("approvalRequest").textContent = data.approval_request
        || "Approve the draft or ask for changes before the final plan is written.";
    $("approvalSection").classList.remove("hidden");
}

function hideApproval() {
    waitingForApproval = false;

    $("approvalSection").classList.add("hidden");
    $("approvalFeedback").value = "";
}

// Both /api/travel and /api/travel/approve return the same shape,
// so one function decides what to show for either response.
function renderOutcome(data) {
    currentThreadId = data.thread_id || currentThreadId;
    const stage = data.requires_approval ? "draft" : "final";

    showWorkflow(data, stage);

    if (data.guardrail_allowed === false) {
        hideResult();
        hideApproval();
        scrollToElement($("workflowSection"));
        return;
    }

    if (data.requires_approval) {
        showResult(data.itinerary || data.answer, currentThreadId, "draft");
        showApproval(data);
    } else {
        hideApproval();
        showResult(data.answer, currentThreadId, "final");
    }
}

/* ---------- API ---------- */

function errorFrom(data, status) {
    if (data && typeof data.error === "string") {
        return data.error;
    }
    // FastAPI uses "detail" for 404s and for request validation errors.
    if (data && typeof data.detail === "string") {
        return data.detail;
    }
    if (data && Array.isArray(data.detail)) {
        return data.detail.map((item) => item.msg).join(" ");
    }
    return `Request failed (${status}).`;
}

async function postJSON(url, payload) {
    let response;

    try {
        response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });
    } catch (networkError) {
        throw new Error("Could not reach the server. Check that it is running and try again.");
    }

    let data = null;

    try {
        data = await response.json();
    } catch (parseError) {
        // The body was not JSON, for example a proxy error page.
    }

    if (!response.ok || !data || !data.success) {
        throw new Error(errorFrom(data, response.status));
    }

    return data;
}

/* ---------- actions ---------- */

async function sendMessage() {
    hideError();

    if (waitingForApproval) {
        showError("You have a draft waiting. Approve it, revise it or discard it before planning another trip.");
        return;
    }

    const message = $("userInput").value.trim();

    if (!message) {
        showError("Describe your trip first, for example where you're going and for how long.");
        return;
    }

    setLoading(true);
    $("workflowSection").classList.add("hidden");
    hideResult();

    try {
        // No thread_id on purpose: every new plan gets its own LangGraph thread,
        // so a draft that was never reviewed cannot interfere with the next request.
        const data = await postJSON("/api/travel", { message: message });
        renderOutcome(data);
    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(false);
    }
}

async function submitApproval(approved) {
    hideError();

    if (!currentThreadId || !waitingForApproval) {
        showError("There is no draft waiting for approval.");
        return;
    }

    const feedbackInput = $("approvalFeedback");
    const feedback = feedbackInput.value.trim();

    if (!approved && !feedback) {
        showError("Write the changes you want, or pick one above the box, before revising.");
        feedbackInput.focus();
        return;
    }

    setApprovalLoading(true, approved);

    try {
        const data = await postJSON("/api/travel/approve", {
            thread_id: currentThreadId,
            approved: approved,
            feedback: feedback
        });

        // the changes were sent, so clear the box for the next round of review
        feedbackInput.value = "";
        renderOutcome(data);
    } catch (error) {
        showError(error.message);
    } finally {
        setApprovalLoading(false);
    }
}

// Adds a common change to the feedback box, after anything already typed.
function addFeedback(text) {
    const input = $("approvalFeedback");
    input.value = input.value.trim() ? `${input.value.trim()} ${text}` : text;
    input.focus();
}

// Clears the screen for a new request. Used by "Plan another trip" and "Discard draft".
function startNewPlan() {
    hideError();
    hideApproval();
    hideResult();
    $("workflowSection").classList.add("hidden");
    currentThreadId = null;

    const input = $("userInput");
    input.value = "";
    scrollToElement(document.querySelector(".planner-card"));
    input.focus();
}

function copyResult() {
    const text = $("resultBox").innerText;

    if (!text) {
        return;
    }

    navigator.clipboard.writeText(text)
        .then(() => {
            const copyBtn = document.querySelector(".copy-btn");
            const oldText = copyBtn.textContent;

            copyBtn.textContent = "Copied";

            setTimeout(() => {
                copyBtn.textContent = oldText;
            }, 1400);
        })
        .catch(() => {
            showError("Could not copy the plan. Select the text and copy it instead.");
        });
}

function downloadPDF() {
    const pdfContent = $("pdfContent");

    if (!latestAnswerMarkdown || !pdfContent) {
        showError("There's no plan to download yet.");
        return;
    }

    if (typeof html2pdf === "undefined") {
        showError("The PDF tool didn't load. Refresh the page and try again.");
        return;
    }

    const downloadBtn = document.querySelector(".download-btn");
    const oldText = downloadBtn.textContent;

    downloadBtn.textContent = "Preparing PDF...";
    downloadBtn.disabled = true;

    const options = {
        margin: 0.5,
        filename: latestStage === "draft" ? "waypoint-draft-plan.pdf" : "waypoint-travel-plan.pdf",
        image: {
            type: "jpeg",
            quality: 0.98
        },
        html2canvas: {
            scale: 2,
            useCORS: true,
            backgroundColor: "#ffffff"
        },
        jsPDF: {
            unit: "in",
            format: "a4",
            orientation: "portrait"
        },
        pagebreak: {
            mode: ["avoid-all", "css", "legacy"]
        }
    };

    html2pdf()
        .set(options)
        .from(pdfContent)
        .save()
        .then(() => {
            downloadBtn.textContent = oldText;
            downloadBtn.disabled = false;
        })
        .catch(() => {
            downloadBtn.textContent = oldText;
            downloadBtn.disabled = false;
            showError("Could not create the PDF. Try again, or use Copy instead.");
        });
}

// Ctrl+Enter (or Cmd+Enter) in the request box starts a new plan.
// Scoped to that box so it never fires from the feedback field.
$("userInput").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        sendMessage();
    }
});

checkHealth();