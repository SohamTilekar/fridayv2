// main.js

// --- Global Variables ---
let fileContents = []; // Global variable to store file information (name and content)
let fileId = null; // Unique ID for the video being uploaded
const CHUNK_SIZE = 512 * 1024; // 0.5MB chunks
let messages = [];
let chats = {};
let current_chat_id = "main";
let sortableInstances = [];
let activeResearchListeners = {}; // To keep track of listeners for cleanup
const socket = io();
// ==========================================================================
// --- Helper Functions ---
// ==========================================================================

/**
 * Creates a button element.
 */
function createButton(className, innerHTML) {
  const button = document.createElement("button");
  button.classList.add(...className.split(" "));
  button.innerHTML = innerHTML;
  return button;
}

/**
 * Copies text to clipboard and provides feedback.
 */
const copyToClipboard = async (text, button) => {
  try {
    await navigator.clipboard.writeText(text);
    button.innerHTML = `<i class="bi bi-clipboard-check"></i> Copied!`;
  } catch (err) {
    console.error("Failed to copy text: ", err);
    button.innerHTML = `<i class="bi bi-clipboard-x-fill"></i> Failed to copy!`;
  } finally {
    setTimeout(() => {
      button.innerHTML = `<i class="bi bi-clipboard"></i> Copy`;
    }, 1500);
  }
};

function handleChatBoxUpdate(updateFunction) {
  return function (...args) {
    const chatBox = document.getElementById("chat-box");
    const isAtBottom =
      chatBox.scrollHeight - chatBox.clientHeight <= chatBox.scrollTop + 1;

    let previousScrollTop = 0;
    if (!isAtBottom) {
      previousScrollTop = chatBox.scrollTop;
    }

    // Call the original function
    const result = updateFunction.apply(this, args);

    // Restore scroll position
    if (isAtBottom) {
      chatBox.scrollTop = chatBox.scrollHeight;
    } else {
      chatBox.scrollTop = previousScrollTop;
    }

    return result;
  };
}
// --- Function to render Topic Tree Recursively ---
function renderTopicTree(topicData, parentElement, level = 0) {
  const topicDiv = document.createElement("div");
  topicDiv.style.marginLeft = `${level * 1.5}rem`;
  topicDiv.classList.add("topic-node");

  const topicHeader = document.createElement("strong");
  topicHeader.textContent = topicData.topic;
  topicDiv.appendChild(topicHeader);

  const topicDetails = document.createElement("div");
  topicDetails.classList.add("topic-details", "ms-2"); // Add some margin
  topicDetails.innerHTML = `
        <small class="text-muted">(ID: ${topicData.id}, Researched: ${topicData.researched ? "Yes" : "No"})</small><br>
        ${topicData.queries ? `<strong>Queries:</strong><pre>${topicData.queries.join("\n")}</pre>` : ""}
        ${topicData.urls && topicData.urls.length > 0 ? `<strong>Sites:</strong><ul>${topicData.urls.map((url) => `<li><a href="${url}" target="_blank">${url}</a></li>`).join("")}</ul>` : ""}
        ${topicData.fetched_content && topicData.fetched_content.length > 0 ? `<strong>Fetched:</strong> ${topicData.fetched_content.length} items` : ""}
    `;
  topicDiv.appendChild(topicDetails);

  parentElement.appendChild(topicDiv);

  if (topicData.sub_topics && topicData.sub_topics.length > 0) {
    topicData.sub_topics.forEach((subTopic) => {
      renderTopicTree(subTopic, parentElement, level + 1);
    });
  }
}

// --- Helper function to render a single step ---
function renderStep(stepData, index, container, functionId) {
  // Added functionId
  const stepDiv = document.createElement("div");
  stepDiv.classList.add("research-step", "mb-2", "pb-2", "border-bottom");
  let stepContent = `<strong>Step ${index + 1}: ${stepData.type}</strong>`;

  if (stepData.type === "thinking" && stepData.content) {
    const thinkingCollapseId = `thinking-collapse-${functionId}-${index}`;
    // Add a toggle button for thinking content
    stepContent += `
            <button class="btn btn-sm btn-outline-secondary ms-2 py-0 px-1" type="button" data-bs-toggle="collapse" data-bs-target="#${thinkingCollapseId}" aria-expanded="false" aria-controls="${thinkingCollapseId}">
                <i class="bi bi-arrows-expand"></i> Toggle Thoughts
            </button>
            <div class="collapse" id="${thinkingCollapseId}">
                <div class="mt-1 mb-0 p-2 bg-dark text-light rounded small border border-secondary">
                    ${marked.parse(stepData.content)}
                </div>
            </div>
        `;
  } else if (stepData.type === "fetch" && stepData.url) {
    stepContent += `<br><small>URL: <a href="${stepData.url}" target="_blank">${stepData.url}</a></small>`;
  } else if (stepData.type === "search" && stepData.query) {
    stepContent += `<br><small>Query: <code>${stepData.query}</code></small>`;
    if (stepData.links && stepData.links.length > 0) {
      stepContent += `<br><small>Found Links:</small><ul class="list-unstyled small mb-0">${stepData.links.map((l) => `<li><a href="${l}" target="_blank">${l}</a></li>`).join("")}</ul>`;
    }
  } else if (stepData.type === "report_gen") {
    stepContent += `<br><small>Generating final report...</small>`;
  }
  // Add more conditions for other step types if needed

  stepDiv.innerHTML = stepContent;
  container.appendChild(stepDiv);
}

function displayDeepResearchDetails(functionId) {
  const msgDiv = document
    .getElementById(`fn-call-${functionId}`)
    ?.closest(".message");
  if (!msgDiv) {
    console.error(`Message div for function ID ${functionId} not found.`);
    return;
  }
  // --- Get Message Data ---
  const msg = messages.find((m) => m.id === msgDiv.id); // Use global messages array
  if (!msg) {
    console.error(
      `Message data for ID ${msgDiv.id} not found in global array.`,
    );
    return;
  }

  const contentItemCall = msg.content.find(
    (c) => c.function_call && c.function_call.id === functionId,
  );
  const contentItemResponse = msg.content.find(
    (c) => c.function_response && c.function_response.id === functionId,
  );

  if (!contentItemCall || !contentItemCall.function_call) {
    console.error(`Function call for ID ${functionId} not found in message.`);
    // Still display response/error if available
    if (contentItemResponse) {
      displayFunctionErrorOrOutput(functionId, contentItemResponse); // You might need this helper
    }
    return;
  }

  const extraData = contentItemCall.function_call.extra_data || {};
  const functionName = contentItemCall.function_call.name;
  const status =
    extraData.status || (contentItemResponse ? "finished" : "running"); // Infer status
  const isRunning = status === "running";
  const isStopping = status === "stopping";
  const isFinished = status === "finished";
  const isStopped = status === "stopped";
  const isError = status === "error";
  const isEditable = isRunning; // Config is editable only when running

  const rightPanel = document.querySelector(".right-panel");
  const attachmentDisplayArea = document.getElementById(
    "attachment-display-area",
  );

  if (rightPanel.classList.contains("d-none")) {
    rightPanel.classList.remove("d-none");
  }
  attachmentDisplayArea.innerHTML = ""; // Clear previous content

  // --- Render Configuration (Foldable) ---
  const configSectionDiv = document.createElement("div");
  configSectionDiv.classList.add(
    "research-section",
    "mb-3",
    "p-3", // Increased padding
    "border",
    "rounded",
    "bg-dark", // Darker background for section
  );

  const configHeader = document.createElement("div");
  configHeader.classList.add(
    "d-flex",
    "justify-content-between",
    "align-items-center",
    "mb-2", // Margin below header
  );
  configHeader.innerHTML = `<h5 class="mb-0 text-light">Configuration</h5>`; // Adjusted header style
  const configToggleButton = createButton(
    "btn btn-sm btn-outline-secondary py-0 px-1",
    '<i class="bi bi-arrows-expand"></i> Toggle',
  );
  configToggleButton.setAttribute("data-bs-toggle", "collapse");
  configToggleButton.setAttribute(
    "data-bs-target",
    `#research-config-collapse-${functionId}`,
  );
  configToggleButton.setAttribute("aria-expanded", "false"); // Start collapsed
  configToggleButton.setAttribute(
    "aria-controls",
    `research-config-collapse-${functionId}`,
  );
  configHeader.appendChild(configToggleButton);
  configSectionDiv.appendChild(configHeader);

  const configCollapseDiv = document.createElement("div");
  configCollapseDiv.classList.add("collapse"); // Default closed
  configCollapseDiv.id = `research-config-collapse-${functionId}`;

  // --- Configuration Inputs ---
  const createInputGroup = (
    labelText,
    inputId,
    currentValue,
    placeholder,
    disabled,
  ) => {
    const group = document.createElement("div");
    group.classList.add("input-group", "input-group-sm", "mb-2");
    group.innerHTML = `
            <span class="input-group-text bg-secondary text-light border-secondary">${labelText}</span>
            <input type="number" min="1" class="form-control bg-dark text-light border-secondary" id="${inputId}" value="${currentValue || ""}" placeholder="${placeholder}" ${disabled ? "disabled" : ""}>
        `;
    return group;
  };

  const maxTopicsGroup = createInputGroup(
    "Max Topics",
    `research-max-topics-${functionId}`,
    extraData.max_topics,
    "None",
    !isEditable,
  );
  configCollapseDiv.appendChild(maxTopicsGroup);

  const maxQueriesGroup = createInputGroup(
    "Max Queries/Topic",
    `research-max-queries-${functionId}`,
    extraData.max_search_queries,
    "5",
    !isEditable,
  );
  configCollapseDiv.appendChild(maxQueriesGroup);

  const maxResultsGroup = createInputGroup(
    "Max Results/Query",
    `research-max-results-${functionId}`,
    extraData.max_search_results,
    "7",
    !isEditable,
  );
  configCollapseDiv.appendChild(maxResultsGroup);

  // --- Stop Button and Status ---
  const stopGroup = document.createElement("div");
  stopGroup.classList.add("d-flex", "align-items-center", "mt-3"); // Added margin top

  let stopButtonClass = "btn-secondary"; // Default
  let stopButtonIcon = "bi-slash-circle-fill";
  let stopButtonText = "Stopped";
  let stopButtonDisabled = true;

  if (isRunning) {
    stopButtonClass = "btn-danger";
    stopButtonIcon = "bi-stop-circle";
    stopButtonText = "Stop";
    stopButtonDisabled = false;
  } else if (isStopping) {
    stopButtonClass = "btn-warning";
    stopButtonIcon = "bi-hourglass-split";
    stopButtonText = "Stopping";
    stopButtonDisabled = true;
  } else if (isFinished) {
    stopButtonClass = "btn-success";
    stopButtonIcon = "bi-check-circle-fill";
    stopButtonText = "Finished";
    stopButtonDisabled = true;
  } else if (isError) {
    stopButtonClass = "btn-danger";
    stopButtonIcon = "bi-exclamation-octagon-fill";
    stopButtonText = "Error";
    stopButtonDisabled = true;
  } // 'stopped' uses the default btn-secondary

  const stopButton = createButton(
    `btn btn-sm ${stopButtonClass}`,
    `<i class="bi ${stopButtonIcon}"></i> ${stopButtonText}`,
  );
  stopButton.id = `research-stop-button-${functionId}`;
  stopButton.disabled = stopButtonDisabled;

  const stopStatusSpan = document.createElement("span");
  stopStatusSpan.classList.add("ms-2", "text-muted", "small");
  stopStatusSpan.id = `research-status-text-${functionId}`;
  stopStatusSpan.textContent = `(${status})`;

  stopGroup.appendChild(stopButton);
  stopGroup.appendChild(stopStatusSpan);
  configCollapseDiv.appendChild(stopGroup);

  configSectionDiv.appendChild(configCollapseDiv);
  attachmentDisplayArea.appendChild(configSectionDiv);

  // --- Render Topic Tree (Foldable) ---
  const topicTreeDiv = document.createElement("div");
  topicTreeDiv.classList.add(
    "research-section",
    "mb-3",
    "p-3",
    "border",
    "rounded",
    "bg-dark",
  );
  const topicHeader = document.createElement("div");
  topicHeader.classList.add(
    "d-flex",
    "justify-content-between",
    "align-items-center",
    "mb-2",
  );
  topicHeader.innerHTML = `<h5 class="mb-0 text-light">Topic Tree</h5>`;
  const topicToggleButton = createButton(
    "btn btn-sm btn-outline-secondary py-0 px-1",
    '<i class="bi bi-arrows-expand"></i> Toggle',
  );
  topicToggleButton.setAttribute("data-bs-toggle", "collapse");
  topicToggleButton.setAttribute(
    "data-bs-target",
    `#research-topic-collapse-${functionId}`,
  );
  topicToggleButton.setAttribute("aria-expanded", "true"); // Start expanded
  topicToggleButton.setAttribute(
    "aria-controls",
    `research-topic-collapse-${functionId}`,
  );
  topicHeader.appendChild(topicToggleButton);
  topicTreeDiv.appendChild(topicHeader);

  const topicCollapseDiv = document.createElement("div");
  topicCollapseDiv.classList.add("collapse", "show"); // Start expanded
  topicCollapseDiv.id = `research-topic-collapse-${functionId}`;
  const topicTreeContainer = document.createElement("div");
  topicTreeContainer.id = `research-topic-container-${functionId}`;
  topicTreeContainer.classList.add("mt-2"); // Add margin top to container
  if (extraData.topic) {
    renderTopicTree(extraData.topic, topicTreeContainer);
  } else {
    topicTreeContainer.innerHTML =
      '<p class="text-muted small">Topic tree not available yet.</p>';
  }
  topicCollapseDiv.appendChild(topicTreeContainer);
  topicTreeDiv.appendChild(topicCollapseDiv);
  attachmentDisplayArea.appendChild(topicTreeDiv);

  // --- Render Steps (Foldable) ---
  const stepsSectionDiv = document.createElement("div");
  stepsSectionDiv.classList.add(
    "research-section",
    "mb-3",
    "p-3",
    "border",
    "rounded",
    "bg-dark",
  );
  const stepsHeader = document.createElement("div");
  stepsHeader.classList.add(
    "d-flex",
    "justify-content-between",
    "align-items-center",
    "mb-2",
  );
  stepsHeader.innerHTML = `<h5 class="mb-0 text-light">Steps</h5>`;
  const stepsToggleButton = createButton(
    "btn btn-sm btn-outline-secondary py-0 px-1",
    '<i class="bi bi-arrows-expand"></i> Toggle',
  );
  stepsToggleButton.setAttribute("data-bs-toggle", "collapse");
  stepsToggleButton.setAttribute(
    "data-bs-target",
    `#research-steps-collapse-${functionId}`,
  );
  stepsToggleButton.setAttribute("aria-expanded", "true"); // Start expanded
  stepsToggleButton.setAttribute(
    "aria-controls",
    `research-steps-collapse-${functionId}`,
  );
  stepsHeader.appendChild(stepsToggleButton);
  stepsSectionDiv.appendChild(stepsHeader);

  const stepsCollapseDiv = document.createElement("div");
  stepsCollapseDiv.classList.add("collapse", "show"); // Start expanded
  stepsCollapseDiv.id = `research-steps-collapse-${functionId}`;
  const stepsContainer = document.createElement("div");
  stepsContainer.id = `research-steps-container-${functionId}`;
  stepsContainer.classList.add("mt-2"); // Add margin top
  if (extraData.steps && extraData.steps.length > 0) {
    extraData.steps.forEach((step, index) => {
      renderStep(step.data, index, stepsContainer, functionId);
    });
  } else {
    stepsContainer.innerHTML =
      '<p class="text-muted small">No steps recorded yet.</p>';
  }
  stepsCollapseDiv.appendChild(stepsContainer);
  stepsSectionDiv.appendChild(stepsCollapseDiv);
  attachmentDisplayArea.appendChild(stepsSectionDiv);

  // --- Render Final Response (Rendered as Markdown) ---
  const responseDiv = document.createElement("div");
  responseDiv.id = `research-response-container-${functionId}`;
  responseDiv.classList.add(
    "research-section",
    "p-3",
    "border",
    "rounded",
    "bg-dark",
  ); // Consistent section styling
  responseDiv.innerHTML = `<h5 class="mb-2 text-light">Final Report</h5>`; // Header

  if (contentItemResponse && contentItemResponse.function_response) {
    if (contentItemResponse.function_response.response?.output) {
      const outputContainer = document.createElement("div");
      outputContainer.classList.add("text-attachment-panel", "bg-darker"); // Reuse style, maybe darker bg
      outputContainer.innerHTML = marked.parse(
        contentItemResponse.function_response.response.output,
      );
      responseDiv.appendChild(outputContainer);
      const copyButton = createCopyButton(
        contentItemResponse.function_response.response.output,
      );
      copyButton.classList.add("mt-2"); // Add margin top to copy button
      responseDiv.appendChild(copyButton);
    } else if (contentItemResponse.function_response.response?.error) {
      const errorContainer = document.createElement("div");
      errorContainer.classList.add("terminal-error", "p-2", "rounded"); // Style error
      errorContainer.textContent =
        contentItemResponse.function_response.response.error;
      responseDiv.appendChild(errorContainer);
    } else if (!isRunning && !isStopping) {
      // Show placeholder only if not running/stopping and no output/error yet
      responseDiv.innerHTML +=
        '<p class="text-muted small mt-2">Report not generated or research stopped early.</p>';
    }
  } else if (!isRunning && !isStopping) {
    // Add placeholder if response object doesn't exist and not running/stopping
    responseDiv.innerHTML +=
      '<p class="text-muted small mt-2">Report not generated yet.</p>';
  }
  attachmentDisplayArea.appendChild(responseDiv);

  // --- Add Event Listeners Conditionally ---
  if (isEditable) {
    // Only add listeners if the research is running
    const maxTopicsInput = document.getElementById(
      `research-max-topics-${functionId}`,
    );
    const maxQueriesInput = document.getElementById(
      `research-max-queries-${functionId}`,
    );
    const maxResultsInput = document.getElementById(
      `research-max-results-${functionId}`,
    );
    const stopBtn = document.getElementById(
      `research-stop-button-${functionId}`,
    );

    const handleMaxTopicsChange = (e) => {
      const value = e.target.value ? parseInt(e.target.value, 10) : null;
      if (value === null || value >= 1) {
        socket.emit(`research-update_max_topics_${functionId}`, value);
      } else {
        e.target.value = extraData.max_topics || ""; // Revert if invalid
      }
    };
    const handleMaxQueriesChange = (e) => {
      const value = e.target.value ? parseInt(e.target.value, 10) : null;
      if (value === null || value >= 1) {
        socket.emit(`research-update_max_queries_${functionId}`, value);
      } else {
        e.target.value = extraData.max_search_queries || ""; // Revert
      }
    };
    const handleMaxResultsChange = (e) => {
      const value = e.target.value ? parseInt(e.target.value, 10) : null;
      if (value === null || value >= 1) {
        socket.emit(`research-update_max_results_${functionId}`, value);
      } else {
        e.target.value = extraData.max_search_results || ""; // Revert
      }
    };
    const handleStopClick = () => {
      socket.emit(`research-stop_${functionId}`);
      // Disable button immediately for responsiveness
      stopBtn.disabled = true;
      stopBtn.classList.remove("btn-danger");
      stopBtn.classList.add("btn-warning"); // Indicate stopping
      stopBtn.innerHTML = `<i class="bi bi-hourglass-split"></i> Stopping`;
      const statusSpan = document.getElementById(
        `research-status-text-${functionId}`,
      );
      if (statusSpan) statusSpan.textContent = `(stopping)`;
    };

    maxTopicsInput?.addEventListener("change", handleMaxTopicsChange);
    maxQueriesInput?.addEventListener("change", handleMaxQueriesChange);
    maxResultsInput?.addEventListener("change", handleMaxResultsChange);
    stopBtn?.addEventListener("click", handleStopClick);

    // Store listeners for cleanup
    activeResearchListeners[functionId] = {
      maxTopics: handleMaxTopicsChange,
      maxQueries: handleMaxQueriesChange,
      maxResults: handleMaxResultsChange,
      stop: handleStopClick,
      cleanup: () => {
        maxTopicsInput?.removeEventListener("change", handleMaxTopicsChange);
        maxQueriesInput?.removeEventListener("change", handleMaxQueriesChange);
        maxResultsInput?.removeEventListener("change", handleMaxResultsChange);
        stopBtn?.removeEventListener("click", handleStopClick);
        delete activeResearchListeners[functionId];
        console.log(`Cleaned up listeners for research ${functionId}`);
      },
    };
  } else {
    // Ensure no listeners are active if not editable
    if (activeResearchListeners[functionId]) {
      activeResearchListeners[functionId].cleanup();
    }
  }

  // Activate the content tab
  const contentTab = new bootstrap.Tab(document.getElementById("content-tab"));
  contentTab.show();
}

// --- Update Socket listener for incremental updates ---
socket.on("research_update", (payload) => {
  const { function_id, update_type, data } = payload;
  // --- Update Configuration Inputs (Keep disabled if viewing details) ---
  // No need to update values if they are disabled when viewing details.
  // The initial display function handles setting the values.

  // --- Update Topic Tree ---
  if (update_type === "topic_tree") {
    const container = document.getElementById(
      `research-topic-container-${function_id}`,
    );
    if (container) {
      container.innerHTML = ""; // Clear previous tree
      renderTopicTree(data, container); // Render the new tree structure
    }
  }
  // --- Append New Step ---
  else if (update_type === "step") {
    const container = document.getElementById(
      `research-steps-container-${function_id}`,
    );
    if (container) {
      const noStepsMsg = container.querySelector("p.text-muted");
      if (noStepsMsg) noStepsMsg.remove();

      const currentStepCount =
        container.querySelectorAll(".research-step").length;
      // Pass function_id to renderStep
      renderStep(data, currentStepCount, container, function_id);
    }
  }
  // --- Update Status (Stop Button, Status Text) ---
  else if (update_type === "status") {
    const stopButton = document.getElementById(
      `research-stop-button-${function_id}`,
    );
    const stopStatus = document.getElementById(
      `research-stop-status-${function_id}`,
    );
    const isStopped =
      data.stopped ||
      data.status === "stopped" ||
      data.status === "finished" ||
      data.status === "error";

    // Update button appearance even if disabled
    if (stopButton) {
      stopButton.disabled = true; // Keep it disabled
      stopButton.classList.remove("btn-danger", "btn-secondary"); // Remove existing color classes
      stopButton.classList.add("btn-secondary"); // Always use disabled style
      const statusText = data.status
        ? data.status.charAt(0).toUpperCase() + data.status.slice(1)
        : "Stopped";
      stopButton.innerHTML = `<i class="bi bi-check-circle-fill"></i> ${statusText}`;
    }
    if (stopStatus) {
      stopStatus.textContent = `(${data.status || (isStopped ? "stopped" : "running")})`;
    }
  }
  // --- Update Final Response Area (Render as Markdown) ---
  else if (update_type === "final_response") {
    const responseContainer = document.getElementById(
      `research-response-container-${function_id}`,
    );
    if (responseContainer) {
      responseContainer.classList.remove("d-none");
      responseContainer.innerHTML = `<h5>Final Report</h5>`;
      if (data.output) {
        const outputDiv = document.createElement("div");
        outputDiv.classList.add("text-attachment-panel");
        // *** Use marked.parse here ***
        outputDiv.innerHTML = marked.parse(data.output);
        responseContainer.appendChild(outputDiv);
        // Add copy button for the original markdown source
        const copyBtn = createCopyButton(data.output);
        responseContainer.appendChild(copyBtn);
      } else if (data.error) {
        const errorDiv = document.createElement("div");
        errorDiv.classList.add("terminal-error");
        errorDiv.textContent = data.error;
        responseContainer.appendChild(errorDiv);
      }
    }
  }
});

// --- Socket listener for cleanup ---
// Keep the existing research_finished listener as is
socket.on("research_finished", (data) => {
  const functionId = data.functionId;
  // Clean up listeners on the client side
  if (
    activeResearchListeners[functionId] &&
    activeResearchListeners[functionId].cleanup
  ) {
    activeResearchListeners[functionId].cleanup(); // Call the stored cleanup function
  } else {
    console.warn(
      `No active listeners found to cleanup for research ${functionId}`,
    );
  }

  // Ensure final button state is set (redundant if status update worked, but safe)
  const stopButton = document.getElementById(
    `research-stop-button-${functionId}`,
  );
  const stopStatus = document.getElementById(
    `research-stop-status-${functionId}`,
  );
  if (stopButton) {
    stopButton.disabled = true;
    if (
      !stopButton.innerHTML.includes("Finished") &&
      !stopButton.innerHTML.includes("Stopped") &&
      !stopButton.innerHTML.includes("Error")
    ) {
      stopButton.classList.remove("btn-danger");
      stopButton.classList.add("btn-secondary");
      stopButton.innerHTML =
        '<i class="bi bi-check-circle-fill"></i> Finished/Stopped';
    }
  }
  if (
    stopStatus &&
    !stopStatus.textContent.includes("finished") &&
    !stopStatus.textContent.includes("stopped") &&
    !stopStatus.textContent.includes("error")
  ) {
    stopStatus.textContent = "(Finished/Stopped)";
  }
});

document.getElementById("chat-box").addEventListener("click", function (event) {
  const clickableTarget = event.target.closest(".fn-call-box-clickable");
  const errorTarget = event.target.closest(".fn-call-box-error");

  if (clickableTarget && !errorTarget) {
    const functionName = clickableTarget.dataset.functionName;
    const functionId = clickableTarget.dataset.functionId;

    if (functionName === "CreateFile") {
      displayCreateFileContent(functionId);
    } else if (functionName === "RunCommand") {
      displayRunCommandOutput(functionId);
    } else if (functionName === "FetchWebsite") {
      displayFetchWebsiteOutput(functionId);
    } else if (functionName === "GetSTDOut") {
      displayGetSTDOutOutput(functionId);
    } else if (functionName === "ReadFile") {
      displayReadFileContent(functionId);
    } else if (functionName === "WriteFile") {
      displayWriteFileContent(functionId);
    } else if (functionName === "DeepResearch") {
      displayDeepResearchDetails(functionId);
    }
  } else if (errorTarget) {
    const functionId = errorTarget.dataset.functionId;
    const functionName = errorTarget.dataset.functionName;
    if (functionName === "DeepResearch") {
      // Also display details even on error for DeepResearch
      displayDeepResearchDetails(functionId);
    } else {
      displayFunctionError(functionId);
    }
  }
});

socket.on("research_finished", (data) => {
  const functionId = data.functionId;
  // Clean up listeners on the client side
  if (activeResearchListeners[functionId]) {
    const maxTopicsInput = document.getElementById(
      `research-max-topics-${functionId}`,
    );
    const maxQueriesInput = document.getElementById(
      `research-max-queries-${functionId}`,
    );
    const maxResultsInput = document.getElementById(
      `research-max-results-${functionId}`,
    );
    const stopBtn = document.getElementById(
      `research-stop-button-${functionId}`,
    );

    maxTopicsInput?.removeEventListener(
      "change",
      activeResearchListeners[functionId].maxTopics,
    );
    maxQueriesInput?.removeEventListener(
      "change",
      activeResearchListeners[functionId].maxQueries,
    );
    maxResultsInput?.removeEventListener(
      "change",
      activeResearchListeners[functionId].maxResults,
    );
    stopBtn?.removeEventListener(
      "click",
      activeResearchListeners[functionId].stop,
    );

    // Update button state if it exists
    if (stopBtn) {
      stopBtn.disabled = true;
      stopBtn.innerHTML = '<i class="bi bi-check-circle-fill"></i> Finished';
      const stopStatus = document.getElementById(
        `research-stop-status-${functionId}`,
      );
      if (stopStatus) stopStatus.textContent = "(Finished/Stopped)";
    }

    delete activeResearchListeners[functionId];
  }
});
// --------------------------------------------------------------------------
// --- Notification Display ---
// --------------------------------------------------------------------------

/**
 * Renders a single notification based on its type.
 */
function renderNotification(notification) {
  const notificationDiv = document.createElement("div");
  notificationDiv.classList.add("notification");
  notificationDiv.dataset.notificationId = notification.id; // Store notification ID
  notificationDiv.dataset.notificationType = notification.type; // Store type for CSS targeting

  if (notification.type === "Mail") {
    let bodyContent = "";
    notification.body.forEach((content) => {
      const iframeContainer = document.createElement("div");
      iframeContainer.classList.add("resizable-iframe-container"); // Add class for styling

      const iframe = document.createElement("iframe");
      iframe.sandbox = "allow-scripts";
      iframe.style.border = "none";
      // iframe width/height will be controlled by the container via CSS
      iframe.srcdoc = content.html ? content.html : content.text;

      iframeContainer.appendChild(iframe);
      bodyContent += iframeContainer.outerHTML;
    });

    notificationDiv.innerHTML = `
          <div class="notification-header">
              <span class="notification-subject">${notification.subject}</span>
              <span class="notification-sender">From: ${notification.sender}</span>
          </div>
          <div class="notification-body">
              ${bodyContent}
          </div>
          <div class="notification-time">
              ${new Date(notification.time).toLocaleTimeString()}
          </div>
      `;
  } else if (notification.type === "Reminder") {
    notificationDiv.innerHTML = `
          <div class="notification-header">
              <span class="notification-subject">Reminder</span>
          </div>
          <div class="notification-body">
              <p>${notification.snipit.text}</p>
          </div>
          <div class="notification-time">
              ${new Date(notification.time).toLocaleTimeString()}
          </div>
      `;
  } else {
    notificationDiv.innerHTML = `
          <div class="notification-header">
              <span class="notification-subject">General Notification</span>
          </div>
          <div class="notification-body">
              <p>${notification.snipit.text}</p>
          </div>
          <div class="notification-time">
              ${new Date(notification.time).toLocaleTimeString()}
          </div>
      `;
  }

  // Add "Mark as Read" button
  const markReadButton = document.createElement("button");
  markReadButton.classList.add("mark-read-button");
  markReadButton.innerHTML = `<i class="bi bi-check-circle"></i> Mark as Read`;
  markReadButton.addEventListener("click", () =>
    markNotificationRead(notification.id),
  );
  notificationDiv.appendChild(markReadButton);

  return notificationDiv;
}

/**
 * Marks a notification as read by removing it from the UI and sending a request to the server.
 */
function markNotificationRead(notificationId) {
  socket.emit("mark_read", { notification_id: notificationId });
}

/**
 * Updates the notification count in the bubble on the "Notifications" tab.
 */
function updateNotificationCount() {
  const notificationCountSpan = document.querySelector(
    "#notification-tab .notification-count",
  );
  const notificationDisplayArea = document.getElementById(
    "notification-display-area",
  );
  const notificationCount =
    notificationDisplayArea.querySelectorAll(".notification").length; // Count existing notifications

  if (notificationCountSpan) {
    notificationCountSpan.textContent = notificationCount;
    notificationCountSpan.style.display = notificationCount ? "inline" : "none"; // Show/hide based on count
  }
}

/**
 * Updates the entire notification display with the given notifications.
 */
function updateNotificationDisplayAll(notifications) {
  const notificationDisplayArea = document.getElementById(
    "notification-display-area",
  );
  notificationDisplayArea.innerHTML = ""; // Clear existing notifications
  notifications.forEach((notification) => {
    const notificationElement = renderNotification(notification);
    notificationDisplayArea.appendChild(notificationElement);
  });
  updateNotificationCount(); // Update the count after rendering
}

/**
 * Updates the notification display area with the given notification.
 */
function updateNotificationDisplay(notification) {
  const notificationDisplayArea = document.getElementById(
    "notification-display-area",
  );
  const notificationElement = renderNotification(notification);
  notificationDisplayArea.prepend(notificationElement); // Add new notifications to the top
  updateNotificationCount(); // Update the count after adding
}

/**
 * Deletes a notification from the UI.
 */
function deleteNotification(notificationId) {
  const notificationElement = document.querySelector(
    `.notification[data-notification-id="${notificationId}"]`,
  );
  if (notificationElement) {
    notificationElement.remove();
  }
  updateNotificationCount(); // Update the count after deleting
}

// ==========================================================================
// --- Core Functionality ---
// ==========================================================================

// --------------------------------------------------------------------------
// --- File Handling ---
// --------------------------------------------------------------------------

/**
 * Reads a file as Base64.
 */
function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => {
      resolve(reader.result.split(",")[1]);
    };

    reader.onerror = () => {
      reject(reader.error);
    };

    reader.readAsDataURL(file);
  });
}

// --------------------------------------------------------------------------
// --- Video Upload Functions ---
// --------------------------------------------------------------------------

/**
 * Generates a unique ID (UUID v4).
 */
function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    var r = (Math.random() * 16) | 0,
      v = c == "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Uploads video in chunks.
 */
const uploadFileInChunks = async (base64File, filename, fileId) => {
  const totalChunks = Math.ceil(base64File.length / CHUNK_SIZE);

  socket.emit("start_upload_file", fileId);

  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, base64File.length);
    const chunk = base64File.substring(start, end);

    socket.emit("upload_file_chunck", {
      id: fileId,
      chunck: chunk,
      idx: i,
      filename: filename,
    });
  }

  socket.emit("end_upload_file", fileId);
};

// ==========================================================================
// --- UI Management ---
// ==========================================================================

// ==========================================================================
// --- Chat History Hierarchy Rendering & Interaction ---
// ==========================================================================

/**
 * Destroys existing SortableJS instances.
 */
function destroySortableInstances() {
  sortableInstances.forEach((instance) => instance.destroy());
  sortableInstances = []; // Clear the array
}

/**
 * Initializes SortableJS on a specific UL element.
 * @param {HTMLUListElement} ulElement - The UL element to initialize SortableJS on.
 * @param {object} allChatsMap - The map of all chats for validation.
 */
function initializeSortableForElement(ulElement, allChatsMap) {
  const instance = new Sortable(ulElement, {
    group: "shared-chats", // Crucial: Same group name for all lists
    animation: 150,
    handle: ".chat-item-name", // Use the name span as the drag handle
    filter: ".no-drag", // Class to prevent dragging 'main'
    preventOnFilter: true,
    fallbackOnBody: true, // Helps with potential clipping issues
    swapThreshold: 0.65, // Threshold for swapping elements

    onEnd: function (evt) {
      const itemEl = evt.item; // The dragged list item (LI)
      const targetList = evt.to; // The list (UL) where the item was dropped
      const sourceList = evt.from; // The list (UL) where the item came from

      const chatId = itemEl.dataset.chatId;

      // Determine the new parent ID. If dropped in root, parent is null.
      // Otherwise, find the parent LI of the target UL.
      let newParentLi = targetList.closest("li.chat-tree-item");
      let newParentId = newParentLi ? newParentLi.dataset.chatId : null;

      // --- Validation ---
      if (chatId === "main") {
        console.warn("Tried to move the 'main' chat. Reverting.");
        renderChatHistoryList(chats); // Re-render to fix visual state
        return;
      }
      if (chatId === newParentId) {
        console.warn("Cannot drop a chat onto itself. Reverting.");
        renderChatHistoryList(chats);
        return;
      }
      // Check if dropping onto a descendant
      if (isDescendant(newParentId, chatId, allChatsMap)) {
        console.warn(
          `Cannot drop chat ${chatId} onto its descendant ${newParentId}. Reverting.`,
        );
        renderChatHistoryList(chats);
        return;
      }

      // Get the original parent ID *before* the drop from the chats map
      const originalParentId = chats[chatId]?.parent_id || null;

      // If the parent hasn't actually changed, do nothing
      // (SortableJS might fire onEnd even if dropped back in the same place)
      if (originalParentId === newParentId && sourceList === targetList) {
        // Also check if the index changed if needed, but for parent change, this is enough
        console.debug(
          "Item dropped in the same list with the same parent. No update needed.",
        );
        return;
      }

      // Send update to backend
      socket.emit("update_chat_parent", {
        chat_id: chatId,
        new_parent_id: newParentId,
      });
      // Important: Don't update the UI here directly. Wait for the 'chat_update'
      // event from the server which confirms the change and re-renders the whole list.
      // This ensures the UI reflects the actual state after backend validation/processing.
    },
  });
  sortableInstances.push(instance); // Store the instance
}

/**
 * Renders the entire chat history list in the history tab.
 * (No changes needed here, it already calls the modified renderSingleChatNode
 * and initializes SortableJS correctly)
 */
function renderChatHistoryList(chatsMap) {
  const historyListContainer = document.getElementById("chat-history-list");
  historyListContainer.innerHTML = "";
  destroySortableInstances();

  const rootUl = document.createElement("ul");
  rootUl.classList.add("chat-tree-root");
  historyListContainer.appendChild(rootUl);

  const mainChat = chatsMap["main"];
  if (mainChat) {
    renderSingleChatNode(mainChat, rootUl, 0, chatsMap, true);
  }

  const rootChats = Object.values(chatsMap).filter(
    (chat) =>
      chat.id !== "main" && (!chat.parent_id || !chatsMap[chat.parent_id]),
  );
  rootChats.sort((a, b) => a.name.localeCompare(b.name));
  rootChats.forEach((chat) => {
    renderSingleChatNode(chat, rootUl, 0, chatsMap, false);
  });

  const allUlElements = historyListContainer.querySelectorAll("ul");
  allUlElements.forEach((ul) => {
    // Ensure ULs always have a minimum height to be better drop targets,
    // especially when empty. Adjust the value as needed.
    ul.style.minHeight = "10px"; // Small min-height
    initializeSortableForElement(ul, chatsMap);
  });

  historyListContainer.removeEventListener(
    "dblclick",
    handleHistoryDoubleClick,
  );
  historyListContainer.addEventListener("dblclick", handleHistoryDoubleClick);

  const activeItem = historyListContainer.querySelector(
    ".active-chat > .chat-item-content",
  );
  if (activeItem) {
    activeItem.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

// Event handler for double-click delegation (no changes needed)
function handleHistoryDoubleClick(event) {
  const targetLi = event.target.closest("li.chat-tree-item");
  if (targetLi && targetLi.dataset.chatId) {
    switchChat(targetLi.dataset.chatId);
  }
}

/**
 * Renders a single chat node and its descendants recursively.
 * Ensures a UL is always present for children, even if empty.
 * Adds a delete button.
 * @param {object} chat - The chat object to render.
 * @param {HTMLUListElement} parentUl - The UL element to append this node to.
 * @param {number} level - The current indentation level.
 * @param {object} allChats - The flat object of all chats { id: chat }.
 * @param {boolean} isMain - Flag to indicate if this is the 'main' chat node.
 */
function renderSingleChatNode(chat, parentUl, level, allChats, isMain = false) {
  const li = document.createElement("li");
  li.dataset.chatId = chat.id;
  li.classList.add("chat-tree-item");
  if (chat.id === current_chat_id) {
    li.classList.add("active-chat");
  }
  if (isMain) {
    li.classList.add("no-drag"); // Prevent dragging/deleting 'main' chat
  }

  const itemContent = document.createElement("div");
  itemContent.classList.add("chat-item-content");
  itemContent.style.paddingLeft = `${level * 1.5}rem`;

  const chatNameSpan = document.createElement("span");
  chatNameSpan.textContent = chat.name || `Chat ${chat.id.substring(0, 6)}...`;
  chatNameSpan.classList.add("chat-item-name");
  chatNameSpan.title = `ID: ${chat.id}\nParent: ${chat.parent_id || "None"}`;

  // --- Action Buttons ---
  const buttonGroup = document.createElement("div");
  buttonGroup.classList.add("chat-item-actions");

  // Branch Button
  const branchButton = createButton(
    "branch-chat-btn btn btn-sm btn-outline-info",
    '<i class="bi bi-diagram-2"></i>',
  );
  branchButton.title = "Create a new branch from here";
  branchButton.addEventListener("click", (e) => {
    e.stopPropagation();
    branchFromChat(chat.id);
  });
  buttonGroup.appendChild(branchButton);

  // Delete Button (only if not 'main')
  if (!isMain) {
    const deleteButton = createButton(
      "delete-chat-btn btn btn-sm btn-outline-danger",
      '<i class="bi bi-trash3"></i>',
    );
    deleteButton.title = "Delete this chat";
    deleteButton.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(chat.id, chat.name);
    });
    buttonGroup.appendChild(deleteButton);
  }

  itemContent.appendChild(chatNameSpan);
  itemContent.appendChild(buttonGroup);
  li.appendChild(itemContent);

  // --- Render Children ---
  // !! Always create the UL for children !!
  const nestedUl = document.createElement("ul");
  nestedUl.classList.add("chat-tree-level", `level-${level + 1}`);
  // Add the UL to the LI *before* populating it
  li.appendChild(nestedUl);

  // Find and render actual children into the created UL
  const children = Object.values(allChats).filter(
    (c) => c.parent_id === chat.id,
  );
  if (children.length > 0) {
    children.sort((a, b) => a.name.localeCompare(b.name));
    children.forEach((child) =>
      renderSingleChatNode(child, nestedUl, level + 1, allChats),
    );
  }
  // If no children, the empty UL remains, acting as a drop target

  parentUl.appendChild(li);
}

/**
 * Prompts for confirmation and sends delete request.
 * @param {string} chatId - ID of the chat to delete.
 * @param {string} chatName - Name of the chat for the prompt.
 */
function deleteChat(chatId, chatName) {
  const confirmation = confirm(
    `Are you sure you want to delete the chat "${chatName || chatId}"?\n\nChildren of this chat will be moved to its parent.\nThis action cannot be undone.`,
  );
  if (confirmation) {
    socket.emit("delete_chat", { chat_id: chatId });
    // UI update will happen via 'chat_update' broadcast
  }
}

/** Helper function to check for circular dependencies before dropping */
function isDescendant(childId, potentialParentId, allChatsMap) {
  if (!potentialParentId) return false; // Cannot be descendant of root
  if (childId === potentialParentId) return false; // Cannot be descendant of self

  let currentId = childId;
  while (currentId) {
    const chat = allChatsMap[currentId];
    if (!chat) return false; // Should not happen with consistent data
    if (chat.parent_id === potentialParentId) {
      return true; // Found potentialParent in the ancestry
    }
    currentId = chat.parent_id; // Move up
  }
  return false; // Reached root without finding
}

/**
 * Switches the current chat view. (No changes needed here, just ensure it's called)
 * @param {string} chatId - The ID of the chat to switch to.
 */
function switchChat(chatId) {
  if (current_chat_id === chatId) return;

  const oldChatId = current_chat_id;
  current_chat_id = chatId;
  localStorage.setItem("current_chat_id", current_chat_id); // Save selection

  // Update visual selection in the history list efficiently
  const historyListContainer = document.getElementById("chat-history-list");
  const oldActive = historyListContainer.querySelector(
    `li[data-chat-id="${oldChatId}"]`,
  );
  const newActive = historyListContainer.querySelector(
    `li[data-chat-id="${current_chat_id}"]`,
  );
  if (oldActive) oldActive.classList.remove("active-chat");
  if (newActive) newActive.classList.add("active-chat");

  // Re-render the main chat box
  updateChatDisplay(messages);
  // Scroll chat box to bottom after switching (or maybe top?)
  const chatBox = document.getElementById("chat-box");
  chatBox.scrollTop = chatBox.scrollHeight;
}
/**
 * Builds the hierarchical list of chats recursively.
 * @param {string | null} parentId - The ID of the parent chat (null for root).
 * @param {object} allChats - The flat object of all chats { id: chat }.
 * @param {number} level - The current indentation level.
 * @returns {HTMLUListElement} The generated UL element for this level.
 */
function buildChatTree(parentId, allChats, level = 0) {
  const ul = document.createElement("ul");
  ul.classList.add("chat-tree-level", `level-${level}`);
  if (level === 0) ul.classList.add("chat-tree-root");

  // Find children of the current parentId
  const children = Object.values(allChats).filter(
    (chat) => chat.parent_id === parentId,
  );

  // Sort children alphabetically by name (optional)
  children.sort((a, b) => a.name.localeCompare(b.name));

  children.forEach((chat) => {
    const li = document.createElement("li");
    li.dataset.chatId = chat.id;
    li.classList.add("chat-tree-item");
    if (chat.id === current_chat_id) {
      li.classList.add("active-chat"); // Mark the selected chat
    }

    const itemContent = document.createElement("div");
    itemContent.classList.add("chat-item-content");
    itemContent.style.paddingLeft = `${level * 1.5}rem`; // Indentation

    const chatNameSpan = document.createElement("span");
    chatNameSpan.textContent =
      chat.name || `Chat ${chat.id.substring(0, 6)}...`;
    chatNameSpan.classList.add("chat-item-name");
    chatNameSpan.title = `ID: ${chat.id}\nParent: ${chat.parent_id || "None"}`; // Tooltip for info

    // --- Select Chat Button ---
    const selectButton = createButton(
      "select-chat-btn btn btn-sm btn-outline-secondary ms-2",
      '<i class="bi bi-arrow-right-circle"></i>',
    );
    selectButton.title = "Switch to this chat";
    selectButton.addEventListener("click", (e) => {
      e.stopPropagation(); // Prevent li click event if needed
      switchChat(chat.id);
    });

    // --- Branch Chat Button ---
    const branchButton = createButton(
      "branch-chat-btn btn btn-sm btn-outline-info ms-1",
      '<i class="bi bi-diagram-2"></i>',
    );
    branchButton.title = "Create a new branch from here";
    branchButton.addEventListener("click", (e) => {
      e.stopPropagation();
      branchFromChat(chat.id);
    });

    itemContent.appendChild(chatNameSpan);
    itemContent.appendChild(selectButton);
    itemContent.appendChild(branchButton);
    li.appendChild(itemContent);

    // Recursively build the tree for children of this chat
    const nestedUl = buildChatTree(chat.id, allChats, level + 1);
    if (nestedUl.hasChildNodes()) {
      li.appendChild(nestedUl); // Append children list only if it has items
    }

    ul.appendChild(li);
  });

  return ul;
}

/**
 * Prompts the user and initiates creating a new chat branch.
 * @param {string} parentId - The ID of the chat to branch from.
 */
function branchFromChat(parentId) {
  const newName = prompt(
    `Enter a name for the new chat branch from "${chats[parentId]?.name || parentId}":`,
  );
  if (newName && newName.trim() !== "") {
    socket.emit("create_chat", { name: newName.trim(), parent_id: parentId });
  } else if (newName !== null) {
    // User entered empty string or only whitespace
    alert("Chat name cannot be empty.");
  }
}

// --------------------------------------------------------------------------
// --- Message Display ---
// --------------------------------------------------------------------------

/**
 * Renders a message in the chat box.  Handles both adding and updating messages.
 */
function renderMessageContent(msgDiv, msg) {
  msgDiv.innerHTML = "";
  // Render each Content item separately
  msg.content.forEach((contentItem) => {
    const contentDiv = document.createElement("div");
    contentDiv.classList.add("message-content");
    if (contentItem.text && contentItem.text.trim() !== "") {
      let textContent = contentItem.text;
      if (contentItem.grounding_metadata) {
        textContent = applyGroundingInfo(
          textContent,
          contentItem.grounding_metadata,
        );
      }
      contentDiv.innerHTML = marked.parse(textContent);
      msgDiv.appendChild(contentDiv);
      // Enhance code blocks/inlines
      enhanceCodeBlocks(contentDiv);
      enhanceCodeInlines(contentDiv);
      if (contentItem.grounding_metadata) initializeTooltips(contentDiv);
    } else if (contentItem.function_call) {
      contentDiv.innerHTML = renderFunctionCall(contentItem.function_call);
      msgDiv.appendChild(contentDiv);
    } else if (contentItem.function_response) {
      renderFunctionResponse(contentItem.function_response);
    } else if (contentItem.attachment) {
      msgDiv.appendChild(createAttachmentElement(contentItem.attachment));
    }
  });
  if (msg.processing)
    msgDiv.innerHTML += `
              <div class="thinking-loader">
                  <div class="dot"></div>
                  <div class="dot"></div>
                  <div class="dot"></div>
              </div>
    `;
}

/**
 * Creates the standard message controls (copy, delete, timestamp).
 */
function createMessageControls(msg) {
  const controlsDiv = document.createElement("div"); // Create a container for the controls
  controlsDiv.classList.add("controls");
  const copyButton = createButton(
    "copy-msg-btn",
    `<i class="bi bi-clipboard"></i> Copy`,
  );
  copyButton.addEventListener("click", () =>
    copyToClipboard(msg.content.map((c) => c.text).join("\n"), copyButton),
  );
  controlsDiv.appendChild(copyButton);

  const deleteButton = createButton(
    "delete-msg-btn",
    `<i class="bi bi-trash-fill"></i> Delete`,
  );
  deleteButton.addEventListener("click", () => deleteMessage(msg.id));
  controlsDiv.appendChild(deleteButton);

  if (msg.role === "user") {
    const retryButton = createButton(
      "retry-msg-btn",
      `<i class="bi bi-arrow-clockwise"></i> Retry`,
    );
    retryButton.addEventListener("click", () => retryMessage(msg));
    controlsDiv.appendChild(retryButton);
  }

  const timestampSpan = document.createElement("span");
  timestampSpan.classList.add("timestamp");
  const timestamp = new Date(msg.time_stamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  timestampSpan.textContent = timestamp;
  controlsDiv.appendChild(timestampSpan);

  return controlsDiv;
}

/**
 * Retries sending a user message.
 */
const retryMessage = (msg) => {
  // Re-send the message content to the server, specifying the original message ID
  // *and* the chat it belongs to (which might be different from current_chat_id if user switched)
  socket.emit("retry_msg", { msg_id: msg.id, chat_id: msg.chat_id }); // Send the message's original chat_id

  // Optionally, provide visual feedback to the user (remains unchanged)
  const msgDiv = document.getElementById(msg.id);
  if (msgDiv) {
    msgDiv.classList.add("message-retrying");
    setTimeout(() => {
      msgDiv.classList.remove("message-retrying");
    }, 2000); // Remove class after 2 seconds
    // The backend will handle deleting subsequent messages in that specific branch (msg.chat_id)
  }
};

const addMessageToChatBox = handleChatBoxUpdate((msg, appendAtTop = false) => {
  // *** ADD FILTERING LOGIC HERE ***
  if (!isMemberMsg(msg, chats[current_chat_id])) {
    console.debug(
      `Skipping add message ${msg.id} (role: ${msg.role}) - not in current branch ${current_chat_id}`,
    );
    return; // Don't add if not in the current branch
  }
  console.debug(
    `Adding message ${msg.id} (role: ${msg.role}) to branch ${current_chat_id}`,
  );

  const chatBox = document.getElementById("chat-box");
  // Check if message already exists (e.g., due to race condition or retry)
  if (document.getElementById(msg.id)) {
    console.warn(
      `Message ${msg.id} already exists in chat box. Updating instead.`,
    );
    updateMessageInChatBox(msg);
    return;
  }

  const msgDiv = document.createElement("div");
  msgDiv.classList.add("message", msg.role === "user" ? "user-msg" : "ai-msg");
  msgDiv.id = msg.id;
  msgDiv.dataset.msg = JSON.stringify(msg); // Store message data

  if (appendAtTop) {
    chatBox.prepend(msgDiv);
  } else {
    chatBox.appendChild(msgDiv);
  }

  renderMessageContent(msgDiv, msg); // Render the message content

  const controlsDiv = createMessageControls(msg); // Create the controls
  msgDiv.appendChild(controlsDiv);
});

const updateMessageInChatBox = handleChatBoxUpdate((msg) => {
  // *** ADD FILTERING LOGIC HERE ***
  if (!isMemberMsg(msg, chats[current_chat_id])) {
    // If the message being updated is no longer relevant to the current view,
    // maybe just remove it? Or ignore the update? Let's ignore for now.
    console.debug(
      `Skipping update for message ${msg.id} - not in current branch ${current_chat_id}`,
    );
    return;
  }
  console.debug(`Updating message ${msg.id} in branch ${current_chat_id}`);

  const msgDiv = document.getElementById(msg.id);
  if (!msgDiv) {
    console.warn(
      `Tried to update message ${msg.id} but it wasn't found in the DOM. Adding it instead.`,
    );
    // Maybe it wasn't added initially due to branch filtering, add it now if relevant
    addMessageToChatBox(msg);
    return;
  }

  // Store the updated message data
  msgDiv.dataset.msg = JSON.stringify(msg);

  // Find the existing controls div to replace later
  const existingControlsDiv = msgDiv.querySelector(".controls");

  // Clear only the content *before* the controls div
  while (
    msgDiv.firstChild &&
    !msgDiv.firstChild.classList?.contains("controls")
  ) {
    msgDiv.removeChild(msgDiv.firstChild);
  }

  // Render the new message content before the controls
  renderMessageContent(msgDiv, msg);

  // Create and append/replace controls
  const newControlsDiv = createMessageControls(msg);
  if (existingControlsDiv) {
    msgDiv.replaceChild(newControlsDiv, existingControlsDiv);
  } else {
    // Append controls if they didn't exist for some reason
    msgDiv.appendChild(newControlsDiv);
  }
});

/**
 * Updates the main chat display, filtering messages based on the current chat branch.
 */
const updateChatDisplay = handleChatBoxUpdate((messagesToDisplay) => {
  const chatBox = document.getElementById("chat-box");
  chatBox.innerHTML = ""; // Clear the chat box first

  // Filter messages based on the current chat branch
  const filteredMessages = messagesToDisplay.filter((msg) =>
    isMemberMsg(msg, chats[current_chat_id]),
  );

  // Render filtered messages from bottom to top for correct order
  for (let i = filteredMessages.length - 1; i >= 0; i--) {
    addMessageToChatBox(filteredMessages[i], true); // Add to the top
  }
});

/**
 * Deletes a message from the server and updates the chat.
 */
const deleteMessage = handleChatBoxUpdate((messageId) => {
  document.getElementById(messageId).remove();
  socket.emit("delete_message", { message_id: messageId });
  return;
});

// --------------------------------------------------------------------------
// --- Code Block Enhancement ---
// --------------------------------------------------------------------------

/**
 * Enhances code blocks with copy button and language label.
 */
function enhanceCodeBlocks(scope) {
  scope.querySelectorAll("pre code").forEach((codeBlock) => {
    const pre = codeBlock.parentElement;
    const copyButton = createButton(
      "copy-code-btn",
      `<i class="bi bi-clipboard"></i> Copy`,
    );
    const langName = document.createElement("span");
    langName.classList.add("lang-label");
    const lang = codeBlock.className.replace("hljs language-", "");
    if (codeBlock.className.indexOf("hljs language-") != -1)
      langName.innerText = lang;

    copyButton.addEventListener("click", () =>
      copyToClipboard(codeBlock.textContent, copyButton),
    );

    codeBlock.classList.add("code-block");

    const container = document.createElement("div");
    container.classList.add("pre-header");
    container.appendChild(langName);
    container.appendChild(copyButton);

    pre.insertBefore(container, pre.firstChild);
  });
}

/**
 * Enhances inline code with a special class.
 */
function enhanceCodeInlines(scope) {
  scope.querySelectorAll("code").forEach((code) => {
    if (!code.classList.contains("code-block")) {
      const highlightedCode = hljs.highlightAuto(code.innerText);
      code.classList.add("code-inline", `language-${highlightedCode.language}`);
      code.innerHTML = highlightedCode.value;
    }
  });
}

// --------------------------------------------------------------------------
// --- Grounding Information ---
// --------------------------------------------------------------------------

/**
 * Applies grounding information to the message content.
 */
function applyGroundingInfo(contentText, groundingMetadata) {
  if (!groundingMetadata) {
    return contentText;
  }

  let result = contentText;

  // Revesing cz the string is going to get updated & the string idx will be wrong
  groundingMetadata.grounding_supports.reverse().forEach((g) => {
    const idx = g["segment"]["end_index"];
    tooltipContent = "";
    g["grounding_chunk_indices"].forEach((c) => {
      const x = groundingMetadata.grounding_chuncks[c];
      tooltipContent += `- [${x[0]}](${x[1]})\n`;
    });
    result = result.substring(0, idx).endsWith("```")
      ? result.substring(0, idx) +
        "\n" +
        `<i class="bi bi-info-circle grounding-marker" data-tooltip="${encodeURIComponent(
          marked.parse(tooltipContent),
        )}"></i>` +
        result.substring(idx)
      : result.substring(0, idx) +
        `<i class="bi bi-info-circle grounding-marker" data-tooltip="${encodeURIComponent(
          marked.parse(tooltipContent),
        )}"></i>` +
        result.substring(idx);
  });

  // First, insert the rendered_content at first_offset if it exists
  if (groundingMetadata.rendered_content) {
    const firstOffset = groundingMetadata.first_offset;
    let newlineBefore = result.lastIndexOf("\n", firstOffset);
    let newlineAfter = result.indexOf("\n", firstOffset);

    // Handle cases where no newline is found before or after
    if (newlineBefore === -1) {
      newlineBefore = 0; // Start of the string
    }
    if (newlineAfter === -1) {
      newlineAfter = result.length; // End of the string
    }

    // Determine the closest newline
    let insertIndex;
    if (firstOffset - newlineBefore <= newlineAfter - firstOffset) {
      insertIndex = newlineBefore;
    } else {
      insertIndex = newlineAfter;
    }
    result =
      result.slice(0, /*exclusive-end*/ insertIndex) +
      groundingMetadata.rendered_content +
      `<div style="height: var(--padding-md)"></div>\n` +
      result.slice(insertIndex);
  }

  return result;
}

/**
 * Initializes tooltips for grounding markers.
 */
function initializeTooltips(element) {
  element.querySelectorAll(".grounding-marker").forEach((marker) => {
    let tooltip = null; // Store the tooltip element
    let timeoutId = null; // Store the timeout ID

    marker.addEventListener("mouseenter", (e) => {
      if (tooltip) {
        clearTimeout(timeoutId); // Clear any pending timeout
        return; // If tooltip already exists, don't create a new one
      }

      const tooltipContent = decodeURIComponent(
        e.target.getAttribute("data-tooltip") || "",
      );

      if (tooltipContent) {
        tooltip = document.createElement("div");
        tooltip.classList.add("grounding-tooltip");
        tooltip.innerHTML = `<div class="tooltip-title">Sources:</div>${tooltipContent}`;
        document.body.appendChild(tooltip);

        const rect = e.target.getBoundingClientRect();
        tooltip.style.left = `${rect.left}px`;
        tooltip.style.top = `${rect.bottom + 5}px`;

        // Add event listener to the tooltip to prevent it from disappearing when the mouse is over it
        tooltip.addEventListener("mouseenter", () => {
          clearTimeout(timeoutId); // Clear any pending timeout
        });

        tooltip.addEventListener("mouseleave", () => {
          startRemoveTimeout();
        });
      }
    });

    marker.addEventListener("mouseleave", () => {
      startRemoveTimeout();
    });

    function startRemoveTimeout() {
      timeoutId = setTimeout(() => {
        removeTooltip();
      }, 200);
    }

    function removeTooltip() {
      if (tooltip) {
        tooltip.remove();
        tooltip = null;
        timeoutId = null;
      }
    }
  });
}

// --------------------------------------------------------------------------
// --- Attachment Display ---
// --------------------------------------------------------------------------

function displayAttachmentInRightPanel(file) {
  const rightPanel = document.querySelector(".right-panel");
  const attachmentDisplayArea = document.getElementById(
    "attachment-display-area",
  );

  if (rightPanel.classList.contains("d-none")) {
    rightPanel.classList.remove("d-none");
  }

  attachmentDisplayArea.innerHTML = ""; // Clear previous content

  if (file.type.startsWith("image/")) {
    const img = document.createElement("img");
    img.classList.add("img-attachment-panel"); // Add class for styling in right panel
    img.src = `data:${file.type};base64,${file.content}`;
    img.alt = file.filename;
    attachmentDisplayArea.appendChild(img);

    const downloadButton = createDownloadButton(file);
    attachmentDisplayArea.appendChild(downloadButton);
  } else if (file.type.startsWith("video/")) {
    const video = document.createElement("video");
    video.classList.add("vid-attachment-panel"); // Add class for styling in right panel
    video.controls = true; // Enable controls in right panel
    video.src = `data:${file.type};base64,${file.content}`;
    video.type = file.type;
    attachmentDisplayArea.appendChild(video);

    const downloadButton = createDownloadButton(file);
    attachmentDisplayArea.appendChild(downloadButton);
  } else if (file.type.startsWith("text/") || file.type === "application/pdf") {
    // Handle text and pdf as text for now
    const textContainer = document.createElement("div");
    textContainer.classList.add("text-attachment-panel");

    let textContent = atob(file.content); // Decode base64 to text

    if (file.type != "text/plain" && file.type.startsWith("text")) {
      highlightedCode = null;
      const language = hljs.getLanguage(file.type.split("/")[1])
        ? file.type.split("/")[1]
        : null;
      if (language !== null)
        highlightedCode = hljs.highlight(textContent, { language });
      else if (file.type == "text/x-python")
        highlightedCode = hljs.highlight(textContent, { language: "py" });
      else highlightedCode = hljs.highlightAuto(textContent);
      textContainer.innerHTML = `<pre><code class="hljs ${highlightedCode.language}">${highlightedCode.value}</code></pre>`;
    } else {
      textContainer.textContent = textContent;
    }
    attachmentDisplayArea.appendChild(textContainer);

    const copyButton = createCopyButton(textContent);
    attachmentDisplayArea.appendChild(copyButton);
    const downloadButton = createDownloadButton(file, textContent); // Pass textContent for download
    attachmentDisplayArea.appendChild(downloadButton);
  }

  // Activate the content tab
  const contentTab = new bootstrap.Tab(document.getElementById("content-tab"));
  contentTab.show();
}

function createDownloadButton(file, textContent = null) {
  const downloadButton = createButton(
    "download-btn",
    `<i class="bi bi-download"></i> Download`,
  );
  downloadButton.classList.add("btn", "btn-secondary");
  downloadButton.addEventListener("click", () => {
    let blob;
    if (textContent !== null) {
      blob = new Blob([textContent], { type: file.type });
    } else {
      blob = base64ToBlob(file.content, file.type);
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = file.filename;
    document.body.appendChild(a); // Required for Firefox
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
  return downloadButton;
}

function createCopyButton(textContent) {
  const copyButton = createButton(
    "copy-text-btn",
    `<i class="bi bi-clipboard"></i> Copy`,
  );
  copyButton.classList.add("btn", "btn-secondary");
  copyButton.addEventListener("click", () => {
    copyToClipboard(textContent, copyButton);
  });
  return copyButton;
}

function base64ToBlob(base64Data, contentType) {
  const byteCharacters = atob(base64Data);
  const byteArrays = [];
  for (let offset = 0; offset < byteCharacters.length; offset += 512) {
    const slice = byteCharacters.slice(offset, offset + 512);
    const byteNumbers = new Array(slice.length);
    for (let i = 0; i < slice.length; i++) {
      byteNumbers[i] = slice.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    byteArrays.push(byteArray);
  }
  return new Blob(byteArrays, { type: contentType });
}

/**
 * Creates an element to display attachments, now handling all file types
 * with preview for images/videos and icon+name for others.
 */
function createAttachmentElement(file) {
  const fileBoxContent = document.createElement("div");
  fileBoxContent.classList.add("attachment-box-content");
  fileBoxContent.dataset.file = JSON.stringify(file);

  if (file.type.startsWith("image/")) {
    const img = document.createElement("img");
    img.classList.add("img-attachment");
    img.src = `data:${file.type};base64,${file.content}`;
    img.alt = file.filename;
    fileBoxContent.appendChild(img); // Append image to fileBoxContent
  } else if (file.type.startsWith("video/")) {
    const video = document.createElement("video");
    video.classList.add("vid-attachment");
    video.alt = file.name;
    video.controls = false;
    video.muted = true;
    video.autoplay = true;
    video.loop = true;
    video.src = `data:${file.type};base64,${file.content}`;
    video.type = file.type;
    fileBoxContent.appendChild(video); // Append video to fileBoxContent
  } else {
    const iconFilenameWrapper = document.createElement("div");
    iconFilenameWrapper.classList.add("icon-filename-wrapper");

    const fileIcon = document.createElement("i");
    fileIcon.classList.add("bi", "bi-file-earmark-text-fill", "doc-icon");
    iconFilenameWrapper.appendChild(fileIcon);

    const fileNameSpan = document.createElement("span");
    fileNameSpan.classList.add("attachment-filename");
    fileNameSpan.textContent = file.filename;
    iconFilenameWrapper.appendChild(fileNameSpan);

    const fileInfoSpan = document.createElement("span");
    fileInfoSpan.classList.add("attachment-fileinfo");
    const fileType = file.type.split("/")[0].toUpperCase();
    const fileSizeKB = ((file.content.length * (3 / 4)) / 1024).toFixed(2);
    fileInfoSpan.textContent = `${fileType} · ${fileSizeKB} KB`;

    fileBoxContent.appendChild(iconFilenameWrapper);
    fileBoxContent.appendChild(fileInfoSpan);
  }
  fileBoxContent.addEventListener("click", function (event) {
    event.stopPropagation(); // Stop event from bubbling up to chat-box
    const fileData = JSON.parse(this.dataset.file); // Retrieve file data
    displayAttachmentInRightPanel(fileData);
  });

  return fileBoxContent;
}

// --------------------------------------------------------------------------
// --- Func Call & Responce Display ---
// --------------------------------------------------------------------------

/**
 * Renders a function call in a box format, similar to the images,
 * with JSON values rendered correctly and omitting empty arguments.
 * @param {Object} functionCall - Object containing name and args properties
 * @returns {string} HTML string for function call display
 */
function renderFunctionCall(functionCall) {
  const name = functionCall.name;
  const args = functionCall.args || {};
  const extra_data = functionCall.extra_data || {};
  const functionId = functionCall.id;
  const iconClass = getFunctionIconClass(name);
  let isClickable = false; // Flag to determine if the box should be clickable
  let displayText = `<span class="fn-name">${name}</span>`; // Default display text

  // --- Specific Function Handling ---

  if (name === "CreateFile") {
    const filename = args.relative_path;
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${filename}</span>`;
    isClickable = true;
  } else if (name === "RunCommand") {
    const command = args.command;
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${command}</span>`;
    isClickable = true;
  } else if (name === "CreateReminder") {
    const message = args.message;
    const intervalType = args.interval_type;
    const intervalInt = args.interval_int;
    const intervalList = args.interval_list;
    const specificTime = args.specific_time;
    const once = args.once;
    displayText = `<span class="fn-name">CreateReminder</span> to <span class="fn-argv">\`${message}\`</span>`;
    if (once) displayText += ` <span class="fn-argk">once</span>`;
    if (intervalType === "minute" && intervalInt > 0)
      displayText += ` every <span class="fn-argv">${intervalInt}</span> <span class="fn-argk">minute(s)</span>`;
    else if (intervalType === "hour" && intervalInt > 0)
      displayText += ` every <span class="fn-argv">${intervalInt}</span> <span class="fn-argk">hour(s)</span>`;
    else if (intervalType === "day") {
      if (specificTime)
        displayText += ` every day at <span class="fn-argv">${specificTime}</span>`;
      else if (intervalInt > 0)
        displayText += ` every <span class="fn-argv">${intervalInt}</span> <span class="fn-argk">day(s)</span>`;
    } else if (
      intervalType === "week" &&
      intervalList &&
      intervalList.length > 0
    ) {
      const days = intervalList.join(", ");
      displayText += ` every <span class="fn-argv">${days}</span> at <span class="fn-argv">${specificTime}</span>`;
    }
    // No response needed inline for CreateReminder
  } else if (name === "CancelReminder") {
    const reminderId = args.reminder_id;
    const foreverOrNext = args.forever_or_next;
    displayText = `<span class="fn-name">CancelReminder</span>`;
    if (foreverOrNext === "forever")
      displayText += ` of ID <span class="fn-argv">${reminderId}</span> <span class="fn-argk">forever</span>`;
    else if (foreverOrNext === "next")
      displayText += ` Next Run of ID <span class="fn-argv">${reminderId}</span>`;
    // No response needed inline for CancelReminder
  } else if (name === "CreateTask") {
    const title = args.title;
    const startDate = args.start_date;
    const startTime = args.start_time;
    const endDate = args.end_date;
    const endTime = args.end_time;
    const allDay = args.allDay;
    const completed = args.completed;
    displayText = `<span class="fn-name">CreateTask</span> to <span class="fn-argv">\`${title}\`</span>`;
    if (startDate) {
      if (startDate === endDate) {
        displayText += ` on <span class="fn-argv">${startDate}</span>`;
        if (startTime && endTime)
          displayText += ` from <span class="fn-argv">${startTime}</span> to <span class="fn-argv">${endTime}</span>`;
        else if (startTime)
          displayText += ` at <span class="fn-argv">${startTime}</span>`;
      } else {
        displayText += ` from <span class="fn-argv">${startDate}</span>`;
        if (startTime)
          displayText += ` at <span class="fn-argv">${startTime}</span>`;
        if (endDate) {
          displayText += ` to <span class="fn-argv">${endDate}</span>`;
          if (endTime)
            displayText += ` until <span class="fn-argv">${endTime}</span>`;
        }
      }
    }
    if (allDay) displayText += ` <span class="fn-argk">allDay</span>`;
    if (completed) displayText += ` <span class="fn-argk">completed</span>`;
    // No response needed inline for CreateTask
  } else if (name === "UpdateTask") {
    const taskId = args.task_id;
    const title = args.title;
    const startDate = args.start_date;
    const startTime = args.start_time;
    const endDate = args.end_date;
    const endTime = args.end_time;
    const allDay = args.allDay;
    const completed = args.completed;
    displayText = `<span class="fn-name">UpdateTask</span> <span class="fn-argk">ID</span> <span class="fn-argv">\`${taskId}\`</span>`;
    if (title)
      displayText += `, <span class="fn-argk">title</span> to <span class="fn-argv">\`${title}\`</span>`;
    if (startDate) {
      if (startDate === endDate) {
        displayText += ` on <span class="fn-argv">${startDate}</span>`;
        if (startTime && endTime)
          displayText += ` from <span class="fn-argv">${startTime}</span> to <span class="fn-argv">${endTime}</span>`;
        else if (startTime)
          displayText += ` at <span class="fn-argv">${startTime}</span>`;
      } else {
        displayText += ` from <span class="fn-argv">${startDate}</span>`;
        if (startTime)
          displayText += ` at <span class="fn-argv">${startTime}</span>`;
        if (endDate) {
          displayText += ` to <span class="fn-argv">${endDate}</span>`;
          if (endTime)
            displayText += ` until <span class="fn-argv">${endTime}</span>`;
        }
      }
    }
    if (allDay !== undefined)
      displayText += ` <span class="fn-argk">allDay</span> to <span class="fn-argv">${allDay}</span>`;
    if (completed !== undefined)
      displayText += ` <span class="fn-argk">completed</span> to <span class="fn-argv">${completed}</span>`;
    // No response needed inline for UpdateTask
  } else if (name === "FetchWebsite") {
    displayText = `<span class="fn-name">${name}</span> from <span class="fn-argv">${args.url}</span>`;
    isClickable = true; // Make clickable to show content
  } else if (name === "RunCommandBackground") {
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${args.command}</span>`;
    // Response will show process ID
  } else if (name === "SendSTDIn") {
    displayText = `<span class="fn-name">${name}</span> to <span class="fn-argv">${args.process_id}</span>: <span class="fn-argv">\`${args.input_str}\`</span>`;
    // No response needed inline
  } else if (name === "GetSTDOut") {
    displayText = `<span class="fn-name">${name}</span> from <span class="fn-argv">${args.process_id}</span>`;
    isClickable = true; // Make clickable to show output
  } else if (name === "CreateFolder") {
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${args.relative_path}</span>`;
    // No response needed inline
  } else if (name === "DeleteFile") {
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${args.relative_path}</span>`;
    // No response needed inline
  } else if (name === "DeleteFolder") {
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${args.relative_path}</span>`;
    // No response needed inline
  } else if (name === "IsProcessRunning") {
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${args.process_id}</span>?`;
    // Response will show True/False
  } else if (name === "KillProcess") {
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${args.process_id}</span>`;
    // No response needed inline
  } else if (name === "ReadFile") {
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${args.relative_path}</span>`;
    isClickable = true; // Make clickable to show content
  } else if (name === "WriteFile") {
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${args.relative_path}</span>`;
    isClickable = true; // Make clickable to show content
  } else if (name === "SendControlC") {
    displayText = `<span class="fn-name">${name}</span> to <span class="fn-argv">${args.process_id}</span>`;
    // No response needed inline
  } else if (name === "DeepResearch") {
    steps = extra_data.steps;
    displayText = `<span class="fn-name">${name}</span> <span class="fn-argv">${extra_data.topic.topic}</span>`;
    steps.forEach((step) => {
      if (step.thoughts) displayText += step.thoughts;
    });
    isClickable = true; // Make clickable to show content
  } else if (name === "LinkAttachment" || name === "Imagen") {
    var placeholder;
    if (name === "LinkAttachment") placeholder = args.relative_paths;
    else placeholder = args.prompt;
    return `
        <div class="fn-call-box" id="fn-call-${functionId}" data-function-name="${name}" data-function-id="${functionId}">
            <span class="placeholder-text">${placeholder}</span>
        </div>
    `;
  }
  // --- Default Rendering (Fallback) ---
  else {
    const formattedArgs = Object.entries(args)
      .filter(
        ([key, value]) => value !== null && value !== undefined && value !== "",
      )
      .map(([key, value]) => {
        let displayValue;
        try {
          displayValue = JSON.stringify(value);
        } catch (e) {
          displayValue = String(value);
        }
        return `<span class="fn-arg"><span class="fn-argk">${key}</span>=<span class="fn-argv">${displayValue}</span></span>`;
      })
      .join(", ");
    displayText += formattedArgs
      ? ` <span class="fn-args"> ${formattedArgs}</span>`
      : "";
  }

  // --- Construct Final HTML ---
  const clickableClass = isClickable ? " fn-call-box-clickable" : "";
  return `
      <div class="fn-call-box${clickableClass}" id="fn-call-${functionId}" data-function-name="${name}" data-function-id="${functionId}">
          <span class="fn-icon"><i class="${iconClass}"></i></span>
          <span class="fn-text">
              ${displayText}
          </span>
          <span class="fn-response">
              <span class="fn-arrow">-></span>
              <div class="thinking-loader">
                  <div class="dot"></div>
                  <div class="dot"></div>
                  <div class="dot"></div>
              </div>
          </span>
      </div>
  `;
}

/**
 * Helper function to determine the icon class based on the function name.
 * You can customize this based on your function names and desired icons.
 * @param {string} functionName
 * @returns {string} Bootstrap Icons class
 */
function getFunctionIconClass(functionName) {
  functionName = functionName.toLowerCase();
  if (
    functionName.includes("read") ||
    functionName.includes("get") ||
    functionName.includes("fetch")
  ) {
    return "bi bi-file-earmark-text"; // Example icon for reading/fetching files or data
  } else if (functionName.includes("execute") || functionName.includes("run")) {
    return "bi bi-play-btn"; // Example icon for executing commands
  } else if (
    functionName.includes("create") ||
    functionName.includes("make") ||
    functionName.includes("generate")
  ) {
    return "bi bi-pencil-square"; // Example icon for creating/writing files
  } else {
    return "bi bi-gear"; // Default gear icon for other functions
  }
}

/**
 * Updates the function call box in-place to display the function response
 * inline, after the '->' indicator.
 * @param {Object} functionResponse - Object containing name and response properties
 */
function renderFunctionResponse(functionResponse) {
  const functionId = functionResponse.id;
  const response = functionResponse.response;
  const isSuccess = response.output !== undefined;
  var showArrow = true;

  const fnResponseSpan = document.querySelector(
    `#fn-call-${functionId} .fn-response`,
  );
  const fnCallBox = document.getElementById(`fn-call-${functionId}`);

  const functionName = fnCallBox.dataset.functionName;

  if (isSuccess) {
    let successText = "";
    if (functionName === "CreateReminder") {
      successText = ` of ID \`${response.output}\``;
      showArrow = false;
    } else if (functionName === "RunCommandBackground") {
      successText = ` Process ID: \`${response.output}\``;
    } else if (functionName === "IsProcessRunning") {
      successText = ` Running: <span class="fn-argv">${response.output}</span>`;
    } else if (
      ["FetchWebsite", "GetSTDOut", "ReadFile", "DeepResearch"].includes(
        functionName,
      )
    ) {
      // For functions where output might be large, just show success
      // Click handler will display full content
      successText = ` Success`;
    } else if (
      [
        "CreateTask",
        "UpdateTask",
        "CancelReminder",
        "CreateFile",
        "RunCommand",
        "SendSTDIn",
        "CreateFolder",
        "DeleteFile",
        "DeleteFolder",
        "KillProcess",
        "WriteFile",
        "SendControlC",
      ].includes(functionName)
    ) {
      // For simple actions, show success message
      successText = ` Success`;
    } else if (functionName === "LinkAttachment" || functionName === "Imagen") {
      fnCallBox.classList = [];
      fnCallBox.innerHTML = "";
      functionResponse.inline_data.forEach((content) => {
        if (content.attachment)
          fnCallBox.appendChild(createAttachmentElement(content.attachment));
        else if (content.text) {
          const contentDiv = document.createElement("div");
          contentDiv.innerHTML = marked.parse(content.text);
          fnCallBox.appendChild(contentDiv);
        }
      });
      return;
    } else {
      // Default success display (e.g., for functions not explicitly handled)
      const formattedContent = JSON.stringify(response.output, null, 2);
      successText = `<span><pre class="fn-inline-response-content">${formattedContent}</pre></span>`;
    }
    fnResponseSpan.innerHTML = successText
      ? `${showArrow ? '<span class="fn-arrow">-></span>' : ""}${successText}`
      : "";
  } else {
    // Handle Error
    fnCallBox.classList.add("fn-call-box-clickable"); // Make error box clickable
    fnCallBox.classList.add("fn-call-box-error");
    fnResponseSpan.innerHTML = ""; // Clear response area on error
  }
}

// Add click handler to chat box
document.getElementById("chat-box").addEventListener("click", function (event) {
  const clickableTarget = event.target.closest(".fn-call-box-clickable");
  const errorTarget = event.target.closest(".fn-call-box-error");

  if (clickableTarget && !errorTarget) {
    const functionName = clickableTarget.dataset.functionName;
    const functionId = clickableTarget.dataset.functionId;

    if (functionName === "CreateFile") {
      displayCreateFileContent(functionId);
    } else if (functionName === "RunCommand") {
      displayRunCommandOutput(functionId);
    } else if (functionName === "FetchWebsite") {
      displayFetchWebsiteOutput(functionId);
    } else if (functionName === "GetSTDOut") {
      displayGetSTDOutOutput(functionId);
    } else if (functionName === "ReadFile") {
      displayReadFileContent(functionId);
    } else if (functionName === "WriteFile") {
      displayWriteFileContent(functionId);
    } else if (functionName === "DeepResearch") {
      displayDeepResearchDetails(functionId);
    }
  } else if (errorTarget) {
    const functionId = errorTarget.dataset.functionId;
    const functionName = errorTarget.dataset.functionName;
    if (functionName === "DeepResearch") {
      displayDeepResearchDetails(functionId);
    } else {
      displayFunctionError(functionId);
    }
  }
});

/**
 * Displays the error of a function call in the right panel.
 * @param {string} functionId - The ID of the function call.
 */
function displayFunctionError(functionId) {
  const msgDiv = document
    .getElementById(`fn-call-${functionId}`)
    .closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItem = msg.content.find(
    (c) => c.function_response && c.function_response.id === functionId,
  );
  if (contentItem && contentItem.function_response) {
    const functionResponse = contentItem.function_response;
    const error = functionResponse.response.error;

    const rightPanel = document.querySelector(".right-panel");
    const attachmentDisplayArea = document.getElementById(
      "attachment-display-area",
    );

    if (rightPanel.classList.contains("d-none")) {
      rightPanel.classList.remove("d-none");
    }

    attachmentDisplayArea.innerHTML = ""; // Clear previous content

    // Display the error message
    const errorContainer = document.createElement("div");
    errorContainer.classList.add("terminal-error");
    errorContainer.textContent = error;
    attachmentDisplayArea.appendChild(errorContainer);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(
      document.getElementById("content-tab"),
    );
    contentTab.show();
  } else {
    console.error(`Function call with ID ${functionId} not found in message.`);
  }
}

/**
 * Displays the content of a CreateFile function call in the right panel.
 * @param {string} functionId - The ID of the function call.
 */
function displayCreateFileContent(functionId) {
  const msgDiv = document
    .getElementById(`fn-call-${functionId}`)
    .closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItem = msg.content.find(
    (c) => c.function_call && c.function_call.id === functionId,
  );

  if (contentItem && contentItem.function_call) {
    const functionCall = contentItem.function_call;
    const fileContent = functionCall.args.content;
    const filename = functionCall.args.relative_path;

    const rightPanel = document.querySelector(".right-panel");
    const attachmentDisplayArea = document.getElementById(
      "attachment-display-area",
    );

    if (rightPanel.classList.contains("d-none")) {
      rightPanel.classList.remove("d-none");
    }

    attachmentDisplayArea.innerHTML = ""; // Clear previous content

    // Display the file path
    const filePathHeader = document.createElement("h6");
    filePathHeader.textContent = `File Path: ${filename}`;
    attachmentDisplayArea.appendChild(filePathHeader);

    // Create a pre element to display the code with highlighting
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.classList.add("hljs"); // Add hljs class for highlighting
    code.textContent = fileContent;
    pre.appendChild(code);
    attachmentDisplayArea.appendChild(pre);

    // Highlight the code
    hljs.highlightElement(code);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(
      document.getElementById("content-tab"),
    );
    contentTab.show();
  } else {
    console.error(`Function call with ID ${functionId} not found in message.`);
  }
}

/**
 * Displays the output of a RunCommand function call in the right panel with a terminal theme.
 * @param {string} functionId - The ID of the function call.
 */
function displayRunCommandOutput(functionId) {
  const msgDiv = document
    .getElementById(`fn-call-${functionId}`)
    .closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemCall = msg.content.find(
    (c) => c.function_call && c.function_call.id === functionId,
  );
  const contentItemResponce = msg.content.find(
    (c) => c.function_response && c.function_response.id === functionId,
  );

  if (
    contentItemCall &&
    contentItemCall.function_call &&
    contentItemResponce &&
    contentItemResponce.function_response
  ) {
    const functionCall = contentItemCall.function_call;
    const functionResponse = contentItemResponce.function_response;
    const command = functionCall.args.command;

    const rightPanel = document.querySelector(".right-panel");
    const attachmentDisplayArea = document.getElementById(
      "attachment-display-area",
    );

    if (rightPanel.classList.contains("d-none")) {
      rightPanel.classList.remove("d-none");
    }

    attachmentDisplayArea.innerHTML = ""; // Clear previous content

    // Display the command
    const commandHeader = document.createElement("div");
    commandHeader.classList.add("terminal-command");
    commandHeader.textContent = `$ ${command}`;
    attachmentDisplayArea.appendChild(commandHeader);

    if (functionResponse.response.output) {
      const output = functionResponse.response.output[0];
      const error = functionResponse.response.output[1];
      const returnCode = functionResponse.response.output[2];

      // Display the output
      const outputContainer = document.createElement("div");
      outputContainer.classList.add("terminal-output");
      outputContainer.textContent = output || "";
      attachmentDisplayArea.appendChild(outputContainer);

      // Display the error
      if (error) {
        const errorContainer = document.createElement("div");
        errorContainer.classList.add("terminal-error");
        errorContainer.textContent = `stderr: ${error}`;
        attachmentDisplayArea.appendChild(errorContainer);
      }

      // Display the return code
      const returnCodeContainer = document.createElement("div");
      returnCodeContainer.classList.add("terminal-return-code");
      returnCodeContainer.textContent = `Return Code: ${returnCode || 0}`;
      attachmentDisplayArea.appendChild(returnCodeContainer);
    } else if (functionResponse.response.error) {
      // Display the error message
      const errorContainer = document.createElement("div");
      errorContainer.classList.add("terminal-error");
      errorContainer.textContent = functionResponse.response.error;
      attachmentDisplayArea.appendChild(errorContainer);
    }

    // Activate the content tab
    const contentTab = new bootstrap.Tab(
      document.getElementById("content-tab"),
    );
    contentTab.show();
  } else {
    console.error(`Function call with ID ${functionId} not found in message.`);
  }
}

/**
 * Displays the output of a FetchWebsite function call in the right panel.
 * @param {string} functionId - The ID of the function call.
 */
function displayFetchWebsiteOutput(functionId) {
  const msgDiv = document
    .getElementById(`fn-call-${functionId}`)
    .closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemResponce = msg.content.find(
    (c) => c.function_response && c.function_response.id === functionId,
  );

  if (
    contentItemResponce &&
    contentItemResponce.function_response &&
    contentItemResponce.function_response.response.output
  ) {
    const output = contentItemResponce.function_response.response.output;

    const rightPanel = document.querySelector(".right-panel");
    const attachmentDisplayArea = document.getElementById(
      "attachment-display-area",
    );

    if (rightPanel.classList.contains("d-none")) {
      rightPanel.classList.remove("d-none");
    }
    attachmentDisplayArea.innerHTML = ""; // Clear previous content

    const outputContainer = document.createElement("div");
    outputContainer.classList.add("text-attachment-panel"); // Use existing style
    outputContainer.innerHTML = marked.parse(output);
    attachmentDisplayArea.appendChild(outputContainer);

    const copyButton = createCopyButton(output);
    attachmentDisplayArea.appendChild(copyButton);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(
      document.getElementById("content-tab"),
    );
    contentTab.show();
  } else {
    console.error(
      `Function response for FetchWebsite with ID ${functionId} not found or has no output.`,
    );
  }
}

/**
 * Displays the output of a GetSTDOut function call in the right panel.
 * @param {string} functionId - The ID of the function call.
 */
function displayGetSTDOutOutput(functionId) {
  const msgDiv = document
    .getElementById(`fn-call-${functionId}`)
    .closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemResponce = msg.content.find(
    (c) => c.function_response && c.function_response.id === functionId,
  );

  if (
    contentItemResponce &&
    contentItemResponce.function_response &&
    contentItemResponce.function_response.response.output
  ) {
    const outputLines = contentItemResponce.function_response.response.output;
    const output = outputLines.join("\n"); // Join lines into a single string

    const rightPanel = document.querySelector(".right-panel");
    const attachmentDisplayArea = document.getElementById(
      "attachment-display-area",
    );

    if (rightPanel.classList.contains("d-none")) {
      rightPanel.classList.remove("d-none");
    }
    attachmentDisplayArea.innerHTML = ""; // Clear previous content

    const outputContainer = document.createElement("div");
    outputContainer.classList.add("terminal-output"); // Use terminal style
    outputContainer.textContent = output;
    attachmentDisplayArea.appendChild(outputContainer);

    const copyButton = createCopyButton(output);
    attachmentDisplayArea.appendChild(copyButton);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(
      document.getElementById("content-tab"),
    );
    contentTab.show();
  } else {
    console.error(
      `Function response for GetSTDOut with ID ${functionId} not found or has no output.`,
    );
  }
}

/**
 * Displays the content of a ReadFile function call in the right panel.
 * @param {string} functionId - The ID of the function call.
 */
function displayReadFileContent(functionId) {
  const msgDiv = document
    .getElementById(`fn-call-${functionId}`)
    .closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemCall = msg.content.find(
    (c) => c.function_call && c.function_call.id === functionId,
  );
  const contentItemResponce = msg.content.find(
    (c) => c.function_response && c.function_response.id === functionId,
  );

  if (
    contentItemCall &&
    contentItemCall.function_call &&
    contentItemResponce &&
    contentItemResponce.function_response &&
    contentItemResponce.function_response.response.output
  ) {
    const filename = contentItemCall.function_call.args.relative_path;
    const fileContent = contentItemResponce.function_response.response.output;

    const rightPanel = document.querySelector(".right-panel");
    const attachmentDisplayArea = document.getElementById(
      "attachment-display-area",
    );

    if (rightPanel.classList.contains("d-none")) {
      rightPanel.classList.remove("d-none");
    }
    attachmentDisplayArea.innerHTML = ""; // Clear previous content

    const filePathHeader = document.createElement("h6");
    filePathHeader.textContent = `File Path: ${filename}`;
    attachmentDisplayArea.appendChild(filePathHeader);

    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.classList.add("hljs");
    code.textContent = fileContent;
    pre.appendChild(code);
    attachmentDisplayArea.appendChild(pre);
    hljs.highlightElement(code); // Apply highlighting

    const copyButton = createCopyButton(fileContent);
    attachmentDisplayArea.appendChild(copyButton);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(
      document.getElementById("content-tab"),
    );
    contentTab.show();
  } else {
    console.error(
      `Function call or response for ReadFile with ID ${functionId} not found or has no output.`,
    );
  }
}

/**
 * Displays the content that was written by a WriteFile function call.
 * @param {string} functionId - The ID of the function call.
 */
function displayWriteFileContent(functionId) {
  const msgDiv = document
    .getElementById(`fn-call-${functionId}`)
    .closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemCall = msg.content.find(
    (c) => c.function_call && c.function_call.id === functionId,
  );

  if (contentItemCall && contentItemCall.function_call) {
    const filename = contentItemCall.function_call.args.relative_path;
    const fileContent = contentItemCall.function_call.args.content; // Get content from the call args

    const rightPanel = document.querySelector(".right-panel");
    const attachmentDisplayArea = document.getElementById(
      "attachment-display-area",
    );

    if (rightPanel.classList.contains("d-none")) {
      rightPanel.classList.remove("d-none");
    }
    attachmentDisplayArea.innerHTML = ""; // Clear previous content

    const filePathHeader = document.createElement("h6");
    filePathHeader.textContent = `File Path: ${filename}`;
    attachmentDisplayArea.appendChild(filePathHeader);

    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.classList.add("hljs");
    code.textContent = fileContent;
    pre.appendChild(code);
    attachmentDisplayArea.appendChild(pre);
    hljs.highlightElement(code); // Apply highlighting

    const copyButton = createCopyButton(fileContent);
    attachmentDisplayArea.appendChild(copyButton);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(
      document.getElementById("content-tab"),
    );
    contentTab.show();
  } else {
    console.error(
      `Function call for WriteFile with ID ${functionId} not found.`,
    );
  }
}

// --------------------------------------------------------------------------
// --- File Handling UI ---
// --------------------------------------------------------------------------

/**
 * Displays file names in boxes with delete buttons and preview.
 */
function displayFileNames() {
  const displayArea = document.getElementById("file-display-area");
  displayArea.innerHTML = "";
  displayArea.style.display = "flex";
  displayArea.style.flexWrap = "wrap";

  fileContents.forEach((fileData, index) => {
    const fileBox = document.createElement("div");
    fileBox.classList.add("file-box");

    const fileDisplayElement = createAttachmentElement(fileData); // Directly use createAttachmentElement
    fileBox.appendChild(fileDisplayElement);

    const deleteButton = document.createElement("button");
    deleteButton.classList.add("delete-file-button");
    deleteButton.innerHTML = '<i class="bi bi-x"></i>';
    deleteButton.addEventListener("click", () => {
      fileContents.splice(index, 1);
      displayFileNames();
    });
    fileBox.appendChild(deleteButton);

    displayArea.appendChild(fileBox);
  });
}

// --------------------------------------------------------------------------
// --- Helper ---
// --------------------------------------------------------------------------

function isMemberMsg(msg, chat) {
  if (msg.chat_id == chat.id) return true;

  // Check if any child chat contains the message
  for (const child of Object.values(chats)) {
    if (child.parent_id == chat.id && isMemberMsg(msg, child)) {
      return true;
    }
  }

  return false;
}

/**
 * Inserts a newline character at the cursor position in the textarea.
 */
function insertNewlineAtCursor(textarea) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const value = textarea.value;
  textarea.value = value.substring(0, start) + "\n" + value.substring(end);
  textarea.selectionStart = textarea.selectionEnd = start + 1;
}

/**
 * Updates the number of rows in the textarea based on the number of lines.
 */
function updateTextareaRows() {
  const textarea = document.getElementById("message-input");
  const lines = textarea.value.split("\n").length;
  textarea.rows = Math.min(lines, 7);
}

// Constants and element references
const modelSelect = document.getElementById("model-select");
// const toggleButtons = document.querySelectorAll('.toggle-button');
const autoSelectButton = document.getElementById("autoselect-tool");
const googleSearchButton = document.getElementById("google-search-tool");

// Global variables to store model compatibility information
let toolSupportedModels = [];
let searchGroundingSupportedModels = [];

// ========== MODEL SELECTION ==========

// Fetch available models from the backend
async function fetchModels() {
  try {
    const response = await fetch("/get_models");
    if (!response.ok) {
      throw new Error("Failed to fetch models");
    }
    const models = await response.json();

    // Clear existing options
    modelSelect.innerHTML = "";

    // Add new options based on API response
    models.forEach((model) => {
      const option = document.createElement("option");
      option.value = model;
      option.textContent = model;
      modelSelect.appendChild(option);
    });
    const option = document.createElement("option");
    option.value = "auto";
    option.textContent = "auto";
    modelSelect.appendChild(option);

    // Load saved selection after populating options
    loadSelectedModel();
  } catch (error) {
    console.error("Error fetching models:", error);
  }
}

// Fetch model compatibility information from the backend
async function fetchModelCompatibility() {
  try {
    const response = await fetch("/get_model_compatibility");
    if (!response.ok) {
      throw new Error("Failed to fetch model compatibility");
    }
    const compatibility = await response.json();

    // Store compatibility information
    toolSupportedModels = compatibility.toolSupportedModels || [];
    searchGroundingSupportedModels =
      compatibility.searchGroundingSupportedModels || [];

    // Update tool availability based on current model after compatibility info is loaded
    updateToolAvailability(modelSelect.value);
  } catch (error) {
    console.error("Error fetching model compatibility:", error);
    // Fallback to hardcoded values if fetch fails
    toolSupportedModels = [
      "Large25",
      "Large20",
      "Medium20",
      "Small20",
      "Large15",
      "Medium15",
      "Small15",
    ];
    searchGroundingSupportedModels = [
      "Large20",
      "Large20",
      "Large15",
      "Medium20",
      "Medium15",
    ];
    updateToolAvailability(modelSelect.value);
  }
}

// Load saved model from local storage
function loadSelectedModel() {
  const savedModel = localStorage.getItem("selectedModel");
  if (
    savedModel &&
    Array.from(modelSelect.options).some((opt) => opt.value === savedModel)
  ) {
    modelSelect.value = savedModel;
  } else if (modelSelect.options.length > 0) {
    // Set first option as default if saved model is invalid
    saveSelectedModel(modelSelect.options[0].value);
  }

  // Send the current selection to the backend
  updateModelSelection(modelSelect.value);
}

// Save selected model to local storage and update backend
function saveSelectedModel(model) {
  localStorage.setItem("selectedModel", model);
  updateModelSelection(model);
}

// Send model selection to the backend
function updateModelSelection(selectedModel) {
  selectedModel = selectedModel ? selectedModel : modelSelect.value;
  socket.emit("set_models", selectedModel == "auto" ? null : selectedModel);
}

// Updated function to dynamically check model compatibility with tools
function updateToolAvailability(selectedModel) {
  // First clear any existing disabled or selected states for a fresh start
  const allButtons = document.querySelectorAll(".toggle-button");

  // Special case for 'auto' selection
  if (selectedModel === "auto") {
    // When auto is selected, check if auto button is selected and update accordingly
    if (autoSelectButton.dataset.state === "selected") {
      // If Auto is selected, disable all other buttons
      allButtons.forEach((button) => {
        if (button.id !== "autoselect-tool") {
          button.dataset.state = "disabled";
        }
      });
    } else {
      // If Auto is not selected, enable all buttons
      allButtons.forEach((button) => {
        if (button.dataset.state === "disabled") {
          button.dataset.state = "unselected";
        }
      });
    }

    saveButtonStates();
    updateToolsSelection();
    return;
  }

  // Check if the selected model supports tools
  const modelSupportsTools = toolSupportedModels.includes(selectedModel);
  const modelSupportsSearch =
    searchGroundingSupportedModels.includes(selectedModel);

  // Check current button states
  const isAutoSelected = autoSelectButton.dataset.state === "selected";
  const isGoogleSearchSelected =
    googleSearchButton && googleSearchButton.dataset.state === "selected";

  // If Auto is selected, apply its rules regardless of model
  if (isAutoSelected) {
    updateToggleButtonStates("auto");
    return;
  }

  // First, handle the Google Search button
  if (googleSearchButton) {
    if (!modelSupportsSearch) {
      // If currently selected but not supported, unselect it
      if (googleSearchButton.dataset.state === "selected") {
        googleSearchButton.dataset.state = "unselected";
      }
      googleSearchButton.dataset.state = "disabled";
    } else if (
      googleSearchButton.dataset.state === "disabled" &&
      modelSupportsSearch
    ) {
      // Re-enable if it was disabled but is now supported
      googleSearchButton.dataset.state = "unselected";
    }
  }

  // If Google is selected, apply its rules to other buttons
  if (isGoogleSearchSelected && modelSupportsSearch) {
    updateToggleButtonStates("google");
    return;
  }

  // Handle reminder and fetch website buttons
  const otherToolButtons = [
    document.getElementById("reminder-tool"),
    document.getElementById("fetch-website-tool"),
    document.getElementById("imagen-tool"),
    document.getElementById("computer-tool"),
  ];

  otherToolButtons.forEach((button) => {
    if (button) {
      if (!modelSupportsTools) {
        // If selected but not supported, unselect it
        if (button.dataset.state === "selected") {
          button.dataset.state = "unselected";
        }
        button.dataset.state = "disabled";
      } else if (button.dataset.state === "disabled" && modelSupportsTools) {
        // Re-enable if it was disabled but is now supported
        button.dataset.state = "unselected";
      }
    }
  });

  saveButtonStates();
  updateToolsSelection();
}

// Handle model selection
modelSelect.addEventListener("change", function () {
  const selectedModel = this.value;
  saveSelectedModel(selectedModel);
  updateToolAvailability(selectedModel);
});

// ========== TOOLS SELECTION ==========

// Load saved button states from local storage
function loadButtonStates() {
  const allButtons = document.querySelectorAll(".toggle-button");
  allButtons.forEach((button) => {
    const savedState = localStorage.getItem(button.id + "-state");
    if (savedState) {
      button.dataset.state = savedState;
    }
  });

  // Apply model compatibility check after loading saved states
  updateToolAvailability(modelSelect.value);
}

// Save button states to local storage
function saveButtonStates() {
  const allButtons = document.querySelectorAll(".toggle-button");
  allButtons.forEach((button) => {
    localStorage.setItem(button.id + "-state", button.dataset.state);
  });
}

// Update toggle button states based on Auto or Google Search selection
function updateToggleButtonStates(selectedTool) {
  const allButtons = document.querySelectorAll(".toggle-button");

  allButtons.forEach((button) => {
    if (selectedTool === "auto") {
      // If Auto is selected, disable all other buttons
      if (button.id !== "autoselect-tool") {
        button.dataset.state = "disabled";
      }
    } else if (selectedTool === "google") {
      // If Google Search is selected, disable Reminder and Fetch
      if (
        button.id === "reminder-tool" ||
        button.id === "fetch-website-tool" ||
        button.id === "imagen-tool" ||
        button.id === "computer-tool"
      ) {
        button.dataset.state = "disabled";
      } else if (
        button.id !== "autoselect-tool" &&
        button.id !== "google-search-tool"
      ) {
        // For any other buttons besides Auto and Google, set to unselected if they were disabled
        if (button.dataset.state === "disabled") {
          button.dataset.state = "unselected";
        }
      }
    } else {
      // No tool is selected, enable all buttons (or keep their state)
      // Only change state if the button was previously disabled
      if (button.dataset.state === "disabled") {
        button.dataset.state = "unselected";
      }
    }
  });

  saveButtonStates();
  updateToolsSelection();
}

// Send tools selection to the backend
function updateToolsSelection() {
  const isAutoSelected = autoSelectButton.dataset.state === "selected";

  if (isAutoSelected) {
    // If Auto is selected, send null to use default behavior
    socket.emit("set_tools", null);
  } else {
    // Get all selected tools
    const selectedTools = [];
    const allButtons = document.querySelectorAll(
      ".toggle-button:not(#autoselect-tool)",
    );

    allButtons.forEach((button) => {
      if (button.dataset.state === "selected") {
        // Convert button ID to tool name format
        const buttonId = button.id.replace("-tool", "");
        let toolName;

        // Map button IDs to tool names
        if (buttonId === "google-search") {
          toolName = "SearchGrounding";
        } else if (buttonId === "reminder") {
          toolName = "Reminder";
        } else if (buttonId === "fetch-website") {
          toolName = "FetchWebsite";
        } else if (buttonId === "computer") {
          toolName = "ComputerTool";
        } else {
          // Use capitalized version of the ID for other tools
          toolName = buttonId
            .split("-")
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
            .join("");
        }

        selectedTools.push(toolName);
      }
    });
    socket.emit("set_tools", selectedTools.length > 0 ? selectedTools : []);
  }
}

// Set up Auto button click handler
autoSelectButton.addEventListener("click", function () {
  if (this.dataset.state === "disabled") {
    return; // Don't do anything if the button is disabled
  }

  const isBeingSelected = this.dataset.state === "unselected";
  this.dataset.state = isBeingSelected ? "selected" : "unselected";

  if (isBeingSelected) {
    // If Auto is being turned ON, disable all other buttons
    updateToggleButtonStates("auto");
  } else {
    // If Auto is being turned OFF, apply model compatibility
    updateToolAvailability(modelSelect.value);
  }
});

// Set up Google Search button click handler
googleSearchButton.addEventListener("click", function () {
  if (this.dataset.state === "disabled") {
    return; // Don't do anything if the button is disabled
  }

  // If Auto is selected, clicking any other button should do nothing
  if (autoSelectButton.dataset.state === "selected") {
    return;
  }

  const isBeingSelected = this.dataset.state === "unselected";
  this.dataset.state = isBeingSelected ? "selected" : "unselected";

  if (isBeingSelected) {
    // If Google Search is being turned ON, apply its rules to other buttons
    updateToggleButtonStates("google");
  } else {
    // If Google Search is being turned OFF, restore compatibility based on model
    updateToolAvailability(modelSelect.value);
  }
});

// Initialize listeners for all buttons
function initializeButtonListeners() {
  // Remove any existing listeners first to avoid duplicates
  const allButtons = document.querySelectorAll(
    ".toggle-button:not(#autoselect-tool):not(#google-search-tool)",
  );

  allButtons.forEach((button) => {
    // Clone the button to remove all event listeners
    const newButton = button.cloneNode(true);
    button.parentNode.replaceChild(newButton, button);

    // Add new event listener
    newButton.addEventListener("click", function () {
      if (this.dataset.state === "disabled") {
        return; // Don't do anything if the button is disabled
      }

      // If Auto is selected or Google is selected, clicking other buttons should do nothing
      if (
        autoSelectButton.dataset.state === "selected" ||
        (googleSearchButton.dataset.state === "selected" &&
          (this.id === "reminder-tool" ||
            this.id === "fetch-website-tool" ||
            this.id === "imagen-tool" ||
            this.id === "computer-tool"))
      ) {
        return;
      }

      this.dataset.state =
        this.dataset.state === "unselected" ? "selected" : "unselected";
      saveButtonStates();
      updateToolsSelection();
    });
  });
}

// Initialize everything when the page loads
document.addEventListener("DOMContentLoaded", function () {
  fetchModels();
  fetchModelCompatibility();

  // Initialize button listeners after a short delay to ensure DOM is ready
  setTimeout(initializeButtonListeners, 500);
});

// Function to calculate and set the max-height of scrollable areas
function setScrollableAreaMaxHeight() {
  const rightPanelTabs = document.getElementById("rightPanelTabs");
  const attachmentDisplayArea = document.getElementById(
    "attachment-display-area",
  );
  const notificationDisplayArea = document.getElementById(
    "notification-display-area",
  );

  if (!rightPanelTabs || !attachmentDisplayArea || !notificationDisplayArea) {
    return; // Exit if elements are not found
  }

  const tabsHeight = rightPanelTabs.offsetHeight;
  const availableHeight = window.innerHeight - tabsHeight - 22; // 20 is for margin

  attachmentDisplayArea.style.maxHeight = `${availableHeight}px`;
  notificationDisplayArea.style.maxHeight = `${availableHeight}px`;
}

// Call the function on page load and window resize
document.addEventListener("DOMContentLoaded", setScrollableAreaMaxHeight);
window.addEventListener("resize", setScrollableAreaMaxHeight);

// ==========================================================================
// --- Socket Communication ---
// ==========================================================================

/**
 * Sends a message with or without file attachments.
 */
const sendMessage = async () => {
  const input = document.getElementById("message-input");
  const message = input.value.trim(); // Trim whitespace

  // Don't send empty messages unless files are attached
  if (!message && fileContents.length === 0) {
    return;
  }

  const filesData = [];
  // Show some indicator that files are uploading
  const sendButton = document.getElementById("send-button");
  const originalButtonContent = sendButton.innerHTML;
  if (fileContents.length > 0) {
    sendButton.innerHTML =
      '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Uploading...';
    sendButton.disabled = true;
  }

  try {
    for (let i = 0; i < fileContents.length; i++) {
      const fileData = fileContents[i];
      fileId = generateUUID(); // Generate a unique ID for this file upload session
      await uploadFileInChunks(fileData.content, fileData.name, fileId);
      filesData.push({
        filename: fileData.name,
        type: fileData.type,
        id: fileId, // Send the generated UUID
      });
    }

    // Clear input and file display *after* successful upload/processing
    input.value = "";
    fileContents = [];
    displayFileNames();
    updateTextareaRows();

    // Emit the message *after* potential file uploads
    socket.emit("send_message", {
      message: message,
      files: filesData,
      chat_id: current_chat_id,
    }); // Include current_chat_id
  } catch (error) {
    console.error("Error during file upload or message sending:", error);
    // Optionally show an error message to the user
    addMessageToChatBox({
      role: "model", // Or a specific 'system' role
      content: [{ text: `Error sending message/files: ${error.message}` }],
      id: `error-${Date.now()}`,
      time_stamp: new Date().toISOString(),
      chat_id: current_chat_id, // Associate error with current chat
    });
  } finally {
    // Restore send button state
    if (fileContents.length === 0) {
      // Only restore if it was changed due to file upload
      sendButton.innerHTML = originalButtonContent;
      sendButton.disabled = false;
    }
  }
};

// --------------------------------------------------------------------------
// --- Socket Event Handlers ---
// --------------------------------------------------------------------------

socket.on("connect", () => {
  current_chat_id = localStorage.getItem("current_chat_id") || "main"; // Load last chat ID
  socket.emit("get_chat_history"); // Request history on connect
  updateModelSelection();
  updateToolsSelection();
});

socket.on("chat_update", (data) => {
  messages = data.messages || [];
  chats = (data.chats || []).reduce((acc, chat) => {
    acc[chat.id] = chat;
    return acc;
  }, {});

  if (!chats["main"]) {
    console.warn("Backend did not provide 'main' chat. Creating default.");
    chats["main"] = { id: "main", name: "Main Chat", parent_id: null };
  }

  if (!chats[current_chat_id]) {
    console.warn(
      `Current chat ID '${current_chat_id}' no longer exists after update. Defaulting to 'main'.`,
    );
    current_chat_id = "main";
    localStorage.setItem("current_chat_id", current_chat_id);
  }

  renderChatHistoryList(chats); // This now handles Sortable re-initialization
  updateChatDisplay(messages);
});

socket.on("updated_msg", (msg) => {
  // Update the message in the global list
  const index = messages.findIndex((m) => m.id === msg.id);
  if (index !== -1) {
    messages[index] = msg;
  } else {
    // If not found, maybe it's a new message that arrived out of order? Add it.
    messages.push(msg);
  }
  // Then let updateMessageInChatBox handle rendering if it's relevant
  updateMessageInChatBox(msg);
});
socket.on("add_message", (msg) => {
  // Add message to the global list first
  messages.push(msg);
  // Then let addMessageToChatBox decide whether to render it based on current_chat_id
  addMessageToChatBox(msg);
});
socket.on("delete_message", (messageId) => {
  // Remove from the global list
  messages = messages.filter((msg) => msg.id !== messageId);
  // Remove from the DOM if it exists
  const msgDiv = document.getElementById(messageId);
  if (msgDiv) {
    handleChatBoxUpdate(() => {
      // Wrap DOM manipulation
      msgDiv.remove();
    })();
  }
});
socket.on("add_notification", (notification) => {
  updateNotificationDisplay(notification);
});

socket.on("notification_update", (notifications) => {
  updateNotificationDisplayAll(notifications);
});

socket.on("delete_notification", (notificationId) => {
  deleteNotification(notificationId);
});

socket.on("take_permission", (msg) => {
  // 1. Find the last message in the chat box
  const chatBox = document.getElementById("chat-box");
  const lastMessageDiv = chatBox.lastElementChild;

  // Check if there are any messages in the chat box
  if (!lastMessageDiv) {
    console.warn("No messages in chat box to append to.");
    return;
  }

  // 2. Create the "permission-request" div
  const permissionRequestDiv = document.createElement("div");
  permissionRequestDiv.classList.add(
    "permission-request",
    "d-flex",
    "align-items-center",
    "justify-content-end" /* Align buttons to the right */,
    "mt-2",
    "p-1" /* Reduced padding */,
  );

  // 3. Create the message text, Agree button, and Deny button
  const messageText =
    document.createElement("span"); /* Use span for inline display */
  messageText.textContent = msg; // Or msg.content if it's an object
  messageText.classList.add(
    "me-2",
    "text-muted",
  ); /* Muted text color, margin right */
  permissionRequestDiv.appendChild(messageText);

  const agreeButton = document.createElement("button");
  agreeButton.textContent = "Agree";
  agreeButton.classList.add(
    "btn",
    "btn-sm",
    "toggle-button",
  ); /* Use toggle-button style */
  agreeButton.addEventListener("click", () => {
    socket.emit("set_permission", true);
    permissionRequestDiv.remove();
  });
  permissionRequestDiv.appendChild(agreeButton);

  const denyButton = document.createElement("button");
  denyButton.textContent = "Deny";
  denyButton.classList.add(
    "btn",
    "btn-sm",
    "toggle-button",
  ); /* Use toggle-button style */
  denyButton.addEventListener("click", () => {
    socket.emit("set_permission", false);
    permissionRequestDiv.remove();
  });
  permissionRequestDiv.appendChild(denyButton);

  // 4. Append the "permission-request" div to the last message
  lastMessageDiv.appendChild(permissionRequestDiv);
});

// --------------------------------------------------------------------------
// --- Right Panel Functions ---
// --------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", function () {
  // Create a resizer element
  const resizer = document.createElement("div");
  resizer.className = "panel-resizer";
  resizer.style.cssText = `
    width: 6px;
    cursor: col-resize;
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    background-color: transparent;
    transition: background-color 0.2s;
    z-index: 100;
  `;

  // Add hover effect
  resizer.addEventListener("mouseover", () => {
    resizer.style.backgroundColor = "rgba(255, 255, 255, 0.1)";
  });

  resizer.addEventListener("mouseout", () => {
    resizer.style.backgroundColor = "transparent";
  });

  // Get panel elements
  const rightPanel = document.querySelector(".right-panel");
  const chatContainer = document.querySelector(".chat-container");

  // Add the resizer to the right panel
  rightPanel.style.position = "relative";
  rightPanel.prepend(resizer);

  // Variables for tracking the resize
  let isResizing = false;
  let lastDownX = 0;
  let panelWasHidden = false; // Track if the panel was hidden

  // Function to start resizing from the right edge
  function startResizeFromEdge(e) {
    if (rightPanel.classList.contains("d-none")) {
      isResizing = true;
      lastDownX = e.clientX;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      panelWasHidden = true; // Indicate that the panel was hidden
      e.preventDefault(); // Prevent text selection during drag
    }
  }

  // Add event listeners for resizing
  resizer.addEventListener("mousedown", (e) => {
    isResizing = true;
    lastDownX = e.clientX; // Store the initial mouse position
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
    panelWasHidden = rightPanel.classList.contains("d-none"); // Check if panel was hidden
  });

  // Add mousedown listener to chatContainer for dragging from the right edge
  chatContainer.addEventListener("mousedown", (e) => {
    // Check if the mouse is near the right edge
    if (e.clientX > chatContainer.offsetWidth - 10 && !isResizing) {
      // Adjust the 10 value for sensitivity
      startResizeFromEdge(e);
    }
  });

  document.addEventListener("mousemove", (e) => {
    if (!isResizing) return;

    const containerWidth =
      document.querySelector(".container-fluid").offsetWidth;
    let rightPanelWidth;
    let chatContainerWidth;

    if (panelWasHidden) {
      // Dragging to show the panel
      rightPanel.classList.remove("d-none");
      rightPanel.classList.add("col-md-4");
      chatContainer.classList.remove("col-md-12");
      chatContainer.classList.add("col-md-8");

      rightPanelWidth = e.clientX;
      chatContainerWidth = containerWidth - e.clientX;
    } else {
      // Regular resizing
      rightPanelWidth = containerWidth - e.clientX;
      chatContainerWidth = e.clientX;
    }

    // Calculate percentage of total width
    let rightPanelPercent = (rightPanelWidth / containerWidth) * 100;
    let chatContainerPercent = (chatContainerWidth / containerWidth) * 100;

    if (chatContainerPercent > 99.9) {
      rightPanel.style.width = `0.1%`;
      chatContainer.style.width = `99.9%`;
      return;
    }

    // Apply the new widths
    rightPanel.style.width = `${rightPanelPercent}%`;
    chatContainer.style.width = `${chatContainerPercent}%`;
  });

  // Function to save the right panel width to local storage
  function saveRightPanelWidth() {
    const containerWidth =
      document.querySelector(".container-fluid").offsetWidth;
    const rightPanelWidth = rightPanel.offsetWidth;
    const paddingLeft = parseFloat(
      window.getComputedStyle(rightPanel).paddingLeft,
    );
    const paddingRight = parseFloat(
      window.getComputedStyle(rightPanel).paddingRight,
    );
    const contentWidth = rightPanelWidth - paddingLeft - paddingRight;
    const rightPanelPercent = (contentWidth / containerWidth) * 100;
    localStorage.setItem("rightPanelWidth", rightPanelPercent.toString());
  }

  // Function to load the right panel width from local storage
  function loadRightPanelWidth() {
    const savedWidth = localStorage.getItem("rightPanelWidth");
    if (savedWidth) {
      const rightPanelPercent = parseFloat(savedWidth)
        ? parseFloat(savedWidth)
        : 0.1;
      rightPanel.style.width = `${rightPanelPercent}%`;
      chatContainer.style.width = `${100 - rightPanelPercent}%`;
    }
  }

  // Call loadRightPanelWidth on page load
  loadRightPanelWidth();

  document.addEventListener("mouseup", () => {
    if (isResizing) {
      isResizing = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      panelWasHidden = false; // Reset the flag

      // Save the right panel width when resizing stops
      saveRightPanelWidth();
    }
  });
  // Initialize Bootstrap Tabs explicitly
  var tabElList = [].slice.call(
    document.querySelectorAll("#rightPanelTabs button"),
  );
  tabElList.forEach((tabEl) => {
    new bootstrap.Tab(tabEl);
  });
  // Save initial width on load in case the user doesn't resize
  window.addEventListener("beforeunload", () => {
    saveRightPanelWidth();
    localStorage.setItem("current_chat_id", current_chat_id);
  });
});

// ==========================================================================
// --- Event Listeners ---
// ==========================================================================

/**
 * Handles the file input change event.
 */
const handleFileInputChange = async () => {
  const fileInput = document.getElementById("file-input");
  if (fileInput.files && fileInput.files.length > 0) {
    const supportedImageTypes = [
      "image/png",
      "image/jpeg",
      "image/webp",
      "image/heic",
      "image/heif",
    ];
    const supportedVidTypes = [
      "video/mp4",
      "video/mpeg",
      "video/mov",
      "video/avi",
      "video/x-flv",
      "video/mpg",
      "video/webm",
      "video/wmv",
      "video/3gpp",
    ];

    for (let i = 0; i < fileInput.files.length; i++) {
      const file = fileInput.files[i];

      if (
        file.type.startsWith("text/") ||
        supportedImageTypes.includes(file.type) ||
        supportedVidTypes.includes(file.type) ||
        file.type === "application/pdf"
      ) {
        try {
          let content = await readFileAsBase64(file);
          fileContents.push({
            name: file.name,
            filename: file.name,
            type: file.type,
            content: content,
          });
        } catch (error) {
          console.error("Error reading file:", error);
          fileContents.push({
            name: file.name,
            filename: file.name,
            type: file.type,
            content: `Error reading file: ${error.message}`,
          });
        }
      } else {
        addMessageToChatBox(document.getElementById("chat-box"), {
          role: "model",
          content: [
            {
              text: `File ${file.name} is not a supported text or image file.`,
            },
          ],
          id: Date.now().toString(36),
        });
      }
    }
  }

  displayFileNames();
};

/**
 * Handles the message input keydown event.
 */
function handleMessageInputKeydown(e) {
  const messageInput = document.getElementById("message-input");
  if (e.key === "Enter" && e.shiftKey) {
    insertNewlineAtCursor(messageInput);
    e.preventDefault();
    updateTextareaRows();
  } else if (e.key === "Enter") {
    e.preventDefault();
    sendMessage();
  }
}

document.getElementById("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage();
});

const messageInput = document.getElementById("message-input");
messageInput.addEventListener("keydown", handleMessageInputKeydown);
messageInput.addEventListener("input", updateTextareaRows);

document
  .getElementById("file-input")
  .addEventListener("change", handleFileInputChange);

// ==========================================================================
// --- Initialization ---
// ==========================================================================

// --------------------------------------------------------------------------
// --- Marked & Highlight.js Initialization ---
// --------------------------------------------------------------------------

// Initialize Marked with Highlight.js
const { Marked } = globalThis.marked;
const { markedHighlight } = globalThis.markedHighlight;

const marked = new Marked(
  markedHighlight({
    emptyLangClass: "hljs",
    langPrefix: "hljs language-",
    highlight(code, lang, info) {
      code = code.replace(
        /<i class="bi bi-info-circle grounding-marker" data-tooltip="%3Cul%3E%0A%3Cli%3E%3Ca%20href%3D%22[^"]*"><\/i>/g,
        "",
      );
      const language = lang && hljs.getLanguage(lang) ? lang : null;
      if (language !== null) return hljs.highlight(code, { language }).value;
      else return hljs.highlightAuto(code).value;
    },
  }),
);

document.addEventListener("DOMContentLoaded", function () {
  fetchModels();
  fetchModelCompatibility();

  // Initialize button listeners after a short delay to ensure DOM is ready
  setTimeout(initializeButtonListeners, 500);

  // Request existing notifications on page load
  socket.emit("get_notifications");
});

// --- Key State Object ---
const keyState = {};

document.addEventListener("keydown", function (event) {
  // --- Check if the focus is on a textarea or input type="text" ---
  const activeElement = document.activeElement;
  if (
    activeElement &&
    (activeElement.tagName === "TEXTAREA" ||
      (activeElement.tagName === "INPUT" && activeElement.type === "text"))
  ) {
    return; // Ignore the key press if focus is on a textarea or text input
  }

  // --- Update Key State ---
  keyState[event.code] = true;

  // --- Right Panel Resize Shortcuts (R + number) ---
  if (keyState["KeyR"]) {
    if (keyState["Digit1"]) {
      resizeRightPanel(10);
    } else if (keyState["Digit2"]) {
      resizeRightPanel(20);
    } else if (keyState["Digit3"]) {
      resizeRightPanel(30);
    } else if (keyState["Digit4"]) {
      resizeRightPanel(40);
    } else if (keyState["Digit5"]) {
      resizeRightPanel(50);
    } else if (keyState["Digit6"]) {
      resizeRightPanel(60);
    } else if (keyState["Digit7"]) {
      resizeRightPanel(70);
    } else if (keyState["Digit8"]) {
      resizeRightPanel(80);
    } else if (keyState["Digit9"]) {
      resizeRightPanel(90);
    } else if (keyState["Digit0"]) {
      resizeRightPanel(0.1);
    }
    return;
  }

  // --- Toggle Tools Shortcuts (t + number) ---
  if (keyState["KeyT"] && !event.ctrlKey) {
    if (event.code === "Digit1") {
      googleSearchButton.click();
    } else if (event.code === "Digit2") {
      const scheduleButton = document.getElementById("reminder-tool");
      scheduleButton.click();
    } else if (event.code === "Digit3") {
      const fetchWebsiteButton = document.getElementById("fetch-website-tool");
      fetchWebsiteButton.click();
    } else if (event.code === "Digit4") {
      const fetchWebsiteButton = document.getElementById("imagen-tool");
      fetchWebsiteButton.click();
    } else if (event.code === "Digit5") {
      const computerToolButton = document.getElementById("computer-tool");
      computerToolButton.click();
    }
    return;
  }
  if (keyState["KeyA"] && !event.ctrlKey) {
    autoSelectButton.click();
    return;
  }

  // --- Toggle Tabs Shortcuts (c, N, S) ---
  if (keyState["KeyC"] && !event.ctrlKey) {
    // Toggle Content tab
    const contentTab = new bootstrap.Tab(
      document.getElementById("content-tab"),
    );
    contentTab.show();
    return;
  } else if (keyState["KeyH"] && !event.ctrlKey) {
    // Toggle History tab
    const historyTab = new bootstrap.Tab(
      document.getElementById("history-tab"),
    );
    historyTab.show();
    return;
  } else if (keyState["KeyN"] && !event.ctrlKey) {
    // Toggle Notification tab
    const notificationTab = new bootstrap.Tab(
      document.getElementById("notification-tab"),
    );
    notificationTab.show();
    return;
  } else if (event.ctrlKey && event.key === "s" && event.code === "KeyS") {
    showShortcutsPopup();
    event.preventDefault(); // Prevent the browser from saving the page
    return;
  } else if (keyState["KeyS"]) {
    // Toggle Schedule tab
    const scheduleTab = new bootstrap.Tab(
      document.getElementById("schedule-tab"),
    );
    scheduleTab.show();
    return;
  }

  // --- Enter Prompt Shortcut (/) ---
  if (event.key === "/" && event.code === "Slash") {
    // Focus on the message input
    document.getElementById("message-input").focus();
    event.preventDefault(); // Prevent the slash from being entered in the input
    return;
  }
  if (event.key === "d" && event.code === "KeyD") {
    // Focus on the message input
    document.getElementById("new-task").focus();
    event.preventDefault(); // Prevent the D from being entered in the input
    return;
  }
  // --- Select Model Shortcuts (m + number) ---
  if (keyState["KeyM"]) {
    const modelSelect = document.getElementById("model-select");
    if (modelSelect) {
      if (keyState["Digit1"]) {
        selectModelByIndex(modelSelect, 0);
      } else if (keyState["Digit2"]) {
        selectModelByIndex(modelSelect, 1);
      } else if (keyState["Digit3"]) {
        selectModelByIndex(modelSelect, 2);
      } else if (keyState["Digit4"]) {
        selectModelByIndex(modelSelect, 3);
      } else if (keyState["Digit5"]) {
        selectModelByIndex(modelSelect, 4);
      } else if (keyState["Digit6"]) {
        selectModelByIndex(modelSelect, 5);
      } else if (keyState["Digit7"]) {
        selectModelByIndex(modelSelect, 6);
      } else if (keyState["Digit8"]) {
        selectModelByIndex(modelSelect, 7);
      }
    }
    return;
  }
  // --- Close Shortcuts Popup (Esc) ---
  if (event.key === "Escape" || event.code === "Escape") {
    const popup = document.querySelector(".shortcuts-popup");
    if (popup) {
      popup.remove();
      document.body.style.overflow = "auto"; // Restore scrolling
    }
    return;
  }
});

document.addEventListener("keyup", function (event) {
  // --- Update Key State ---
  keyState[event.code] = false;
});

document.addEventListener("visibilitychange", function () {
  if (document.hidden) {
    // Reset keyState when the page becomes hidden
    for (const key in keyState) {
      if (keyState.hasOwnProperty(key)) {
        keyState[key] = false;
      }
    }
  }
});

/**
 * Resizes the right panel to the specified percentage.
 * @param {number} percentage - The percentage to resize the right panel to.
 */
function resizeRightPanel(percentage) {
  const rightPanel = document.querySelector(".right-panel");
  const chatContainer = document.querySelector(".chat-container");
  const containerWidth = document.querySelector(".container-fluid").offsetWidth;

  const rightPanelWidth = (percentage / 100) * containerWidth;
  const chatContainerWidth = containerWidth - rightPanelWidth;

  rightPanel.style.width = `${percentage}%`;
  chatContainer.style.width = `${100 - percentage}%`;

  // Save the right panel width to local storage
  localStorage.setItem("rightPanelWidth", percentage.toString());
}

/**
 * Selects the option at the specified index in the select element.
 * @param {HTMLSelectElement} selectElement - The select element.
 * @param {number} index - The index of the option to select.
 */
function selectModelByIndex(selectElement, index) {
  if (
    selectElement &&
    selectElement.options &&
    index >= 0 &&
    index < selectElement.options.length
  ) {
    selectElement.selectedIndex = index;
    // Dispatch a change event to trigger any associated actions
    selectElement.dispatchEvent(new Event("change"));
  }
}

/**
 * Shows a popup window with a list of available shortcuts.
 */
function showShortcutsPopup() {
  // Create the popup content
  const shortcuts = [
    "`r + [1-9]`: Resize right panel (10%-90%)",
    "`t + [1-4]`: Toggle tools (Auto, Search, Schedule, Fetch, Computer)",
    "`c`: Toggle Content tab",
    "`n`: Toggle Notification tab",
    "`h`: Toggle Chat History tab",
    "`s`: Toggle Schedule tab",
    "`/`: Focus on message input",
    "`m + [1-8]`: Select model by index",
    "`Ctrl + S`: Show shortcuts popup",
  ];

  const popupContent = shortcuts
    .map((shortcut) => marked.parse(shortcut))
    .join("");

  // Create the popup element
  const popup = document.createElement("div");
  popup.classList.add("shortcuts-popup");
  popup.innerHTML = `
        <div class="shortcuts-popup-content">
            <h3>Keyboard Shortcuts</h3>
            ${popupContent}
            <button class="close-popup-button">X</button>
        </div>
    `;

  // Add the popup to the document body
  document.body.appendChild(popup);

  // Add event listener to the close button
  const closeButton = popup.querySelector(".close-popup-button");
  closeButton.addEventListener("click", function () {
    popup.remove();
  });

  // Prevent scrolling of the main page when the popup is open
  document.body.style.overflow = "hidden";

  // Restore scrolling when the popup is closed
  popup.addEventListener("transitionend", function () {
    if (!document.body.contains(popup)) {
      document.body.style.overflow = "auto";
    }
  });
}
