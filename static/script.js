/*
 * Waypoint AI frontend
 *
 * Flow: Generate Draft -> guardrail + supervisor + specialist agents
 *       -> review the draft -> approve or revise -> final plan
 */

let currentThreadId = null;   // thread of the plan currently on screen
let latestAnswerMarkdown = "";
let latestStage = "final";    // "draft" or "final"
let waitingForApproval = false;

// The supervisor returns agent ids. "source" names the MCP server the agent
// gets its live data from; agents without a source only reason over that data.
const AGENT_META = {
    flight_agent: { label: "✈️ Flight Agent", source: "Aviationstack MCP" },
    hotel_agent: { label: "🏨 Hotel Agent", source: "Tavily MCP" },
    weather_agent: { label: "🌦️ Weather Agent", source: "Custom Weather MCP" },
    budget_agent: { label: "💰 Budget Agent" },
    itinerary_agent: { label: "🗓️ Itinerary Agent" }
};

function $(id) {
    return document.getElementById(id);
}

function scrollToElement(element, block = "start") {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    element.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: block });
}

function setPrompt(text) {
    $("userInput").value = text;
}

/* ---------- loading states ---------- */

function setLoading(isLoading) {
    $("sendBtn").disabled = isLoading;
    $("btnText").classList.toggle("hidden", isLoading);
    $("btnLoader").classList.toggle("hidden", !isLoading);
    $("loadingNote").classList.toggle("hidden", !isLoading);
}

function setApprovalLoading(isLoading, approved = true) {
    const approveBtn = $("approveBtn");
    const reviseBtn = $("reviseBtn");

    // Remember the original labels so they can be restored afterwards.
    [approveBtn, reviseBtn].forEach((button) => {
        if (!button.dataset.label) {
            button.dataset.label = button.textContent.trim();
        }
    });

    $("sendBtn").disabled = isLoading;
    approveBtn.disabled = isLoading;
    reviseBtn.disabled = isLoading;

    if (isLoading) {
        (approved ? approveBtn : reviseBtn).textContent = approved
            ? "Generating final plan..."
            : "Applying your feedback...";
    } else {
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

function renderMarkdown(element, markdown) {
    if (typeof marked !== "undefined") {
        element.innerHTML = marked.parse(markdown || "");
    } else {
        element.innerText = markdown || "";
    }
}

function showWorkflow(data) {
    const blocked = data.guardrail_allowed === false;
    const badge = $("guardrailBadge");
    const route = $("agentRoute");

    $("workflowTitle").textContent = blocked ? "Request Blocked" : "Execution Plan";
    $("workflowSubtitle").textContent = blocked
        ? "The guardrail stopped this request before any agent ran."
        : "Chosen by the supervisor agent for your request.";

    $("supervisorReasoning").textContent = blocked
        ? (data.supervisor_reasoning || data.answer || "Waypoint only helps with travel planning.")
        : (data.supervisor_reasoning || "Supervisor routing completed.");

    badge.textContent = blocked ? "Guardrail blocked" : "Guardrail passed";
    badge.classList.toggle("blocked", blocked);

    // One stop per selected agent, in the order they run.
    route.replaceChildren();

    if (!blocked) {
        (data.selected_agents || []).forEach((agent) => {
            const meta = AGENT_META[agent] || { label: agent };

            const stop = document.createElement("li");
            stop.className = "route-stop";

            const name = document.createElement("span");
            name.className = "route-stop-name";
            name.textContent = meta.label;
            stop.appendChild(name);

            if (meta.source) {
                const source = document.createElement("span");
                source.className = "route-stop-source";
                source.textContent = `via ${meta.source}`;
                stop.appendChild(source);
            }

            route.appendChild(stop);
        });
    }

    $("workflowSection").classList.remove("hidden");
}

function showResult(markdown, threadId, stage) {
    latestAnswerMarkdown = markdown || "";
    latestStage = stage;

    renderMarkdown($("resultBox"), latestAnswerMarkdown);

    $("resultTitle").textContent = stage === "draft"
        ? "Draft Travel Plan"
        : "Your Final AI Travel Plan";
    $("resultHint").classList.toggle("hidden", stage !== "draft");
    $("threadInfo").textContent = `Thread ID: ${threadId}`;

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
        || "Approve the draft or provide feedback before the final plan is generated.";
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
    showWorkflow(data);

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
        showError("Please approve or revise the current draft before starting another plan.");
        return;
    }

    const message = $("userInput").value.trim();

    if (!message) {
        showError("Please enter your travel request first.");
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
        showError("Please enter revision feedback before requesting changes.");
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
        renderOutcome(data);
    } catch (error) {
        showError(error.message);
    } finally {
        setApprovalLoading(false);
    }
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

            copyBtn.textContent = "Copied!";

            setTimeout(() => {
                copyBtn.textContent = oldText;
            }, 1400);
        })
        .catch(() => {
            showError("Could not copy result.");
        });
}

function downloadPDF() {
    const pdfContent = $("pdfContent");

    if (!latestAnswerMarkdown || !pdfContent) {
        showError("No travel plan available to download.");
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
            showError("Could not download PDF.");
        });
}

// Ctrl+Enter (or Cmd+Enter) in the request box starts a new draft.
// Scoped to that box so it never fires from the feedback field.
$("userInput").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        sendMessage();
    }
});