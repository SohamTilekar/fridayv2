// main.js

// --- Global Variables ---
let fileContents = []; // Global variable to store file information (name and content)
let fileId = null; // Unique ID for the video being uploaded
const CHUNK_SIZE = 512 * 1024; // 0.5MB chunks
// ==========================================================================
// --- Helper Functions ---
// ==========================================================================

/**
 * Creates a button element.
 */
function createButton(className, innerHTML) {
  const button = document.createElement("button");
  button.classList.add(className);
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
    notification.body.forEach(content => {
      const iframeContainer = document.createElement('div');
      iframeContainer.classList.add('resizable-iframe-container'); // Add class for styling

      const iframe = document.createElement('iframe');
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
  markReadButton.addEventListener("click", () => markNotificationRead(notification.id));
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
  const notificationCountSpan = document.querySelector('#notification-tab .notification-count');
  const notificationDisplayArea = document.getElementById("notification-display-area");
  const notificationCount = notificationDisplayArea.querySelectorAll('.notification').length; // Count existing notifications

  if (notificationCountSpan) {
    notificationCountSpan.textContent = notificationCount;
    notificationCountSpan.style.display = notificationCount ? 'inline' : 'none'; // Show/hide based on count
  }
}

/**
* Updates the entire notification display with the given notifications.
*/
function updateNotificationDisplayAll(notifications) {
  const notificationDisplayArea = document.getElementById("notification-display-area");
  notificationDisplayArea.innerHTML = ""; // Clear existing notifications
  notifications.forEach(notification => {
    const notificationElement = renderNotification(notification);
    notificationDisplayArea.appendChild(notificationElement);
  });
  updateNotificationCount(); // Update the count after rendering
}

/**
* Updates the notification display area with the given notification.
*/
function updateNotificationDisplay(notification) {
  const notificationDisplayArea = document.getElementById("notification-display-area");
  const notificationElement = renderNotification(notification);
  notificationDisplayArea.prepend(notificationElement); // Add new notifications to the top
  updateNotificationCount(); // Update the count after adding
}

/**
* Deletes a notification from the UI.
*/
function deleteNotification(notificationId) {
  const notificationElement = document.querySelector(`.notification[data-notification-id="${notificationId}"]`);
  if (notificationElement) {
    notificationElement.remove();
  }
  updateNotificationCount(); // Update the count after deleting
}

// ==========================================================================
// --- Core Functionality ---
// ==========================================================================

// --------------------------------------------------------------------------
// --- Socket Communication ---
// --------------------------------------------------------------------------

const socket = io();

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

// --------------------------------------------------------------------------
// --- Message Display ---
// --------------------------------------------------------------------------

/**
 * Renders a message in the chat box.  Handles both adding and updating messages.
 */
function renderMessageContent(msgDiv, msg) {
  msgDiv.innerHTML = ""
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
      if (contentItem.grounding_metadata)
        initializeTooltips(contentDiv);
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
    `
}

/**
 * Creates the standard message controls (copy, delete, timestamp).
 */
function createMessageControls(msg) {
  const controlsDiv = document.createElement("div"); // Create a container for the controls
  controlsDiv.classList.add("controls")
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
  // Re-send the message content to the server
  socket.emit("retry_msg", msg.id);

  // Optionally, provide visual feedback to the user
  const msgDiv = document.getElementById(msg.id);
  if (msgDiv) {
    msgDiv.classList.add("message-retrying");
    setTimeout(() => {
      msgDiv.classList.remove("message-retrying");
    }, 2000); // Remove class after 2 seconds
  }
};

const addMessageToChatBox = handleChatBoxUpdate((msg, appendAtTop = false) => {
  const chatBox = document.getElementById("chat-box");
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
  const msgDiv = document.getElementById(msg.id);
  if (!msgDiv) return;

  renderMessageContent(msgDiv, msg); // Re-render the message content

  // Replace existing controls with updated ones
  const existingControls = msgDiv.querySelector(
    ".copy-msg-btn, .delete-msg-btn, .timestamp",
  );
  if (existingControls) {
    msgDiv.removeChild(existingControls.parentNode); // Remove the parent div
  }
  const controlsDiv = createMessageControls(msg); // Create the controls
  msgDiv.appendChild(controlsDiv);
});

/**
 * Deletes a message from the server and updates the chat.
 */
const deleteMessage = handleChatBoxUpdate((messageId) => {
  document.getElementById(messageId).remove();
  socket.emit("delete_message", { message_id: messageId });
  return;
});

/**
 * Updates the entire chat display with the given history.
 */
const updateChatDisplay = handleChatBoxUpdate((history) => {
  const chatBox = document.getElementById("chat-box");
  chatBox.innerHTML = "";
  // Render messages from bottom to top
  for (let i = history.length - 1; i >= 0; i--) {
    addMessageToChatBox(history[i], true); // Append at the top
  }
  chatBox.scrollTop = chatBox.scrollHeight;
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
  const rightPanel = document.querySelector('.right-panel');
  const attachmentDisplayArea = document.getElementById('attachment-display-area');

  if (rightPanel.classList.contains('d-none')) {
    rightPanel.classList.remove('d-none');
  }

  attachmentDisplayArea.innerHTML = ''; // Clear previous content

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

  } else if (file.type.startsWith("text/") || file.type === "application/pdf") { // Handle text and pdf as text for now
    const textContainer = document.createElement('div');
    textContainer.classList.add('text-attachment-panel');

    let textContent = atob(file.content); // Decode base64 to text

    if (file.type != "text/plain" && file.type.startsWith("text")) {
      highlightedCode = null
      const language = hljs.getLanguage(file.type.split("/")[1]) ? file.type.split("/")[1] : null;
      if (language !== null)
        highlightedCode = hljs.highlight(textContent, { language });
      else if (file.type == "text/x-python")
        highlightedCode = hljs.highlight(textContent, { language: "py" });
      else
        highlightedCode = hljs.highlightAuto(textContent);
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
  const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
  contentTab.show();
}

function createDownloadButton(file, textContent = null) {
  const downloadButton = createButton("download-btn", `<i class="bi bi-download"></i> Download`);
  downloadButton.classList.add("btn", "btn-secondary");
  downloadButton.addEventListener('click', () => {
    let blob;
    if (textContent !== null) {
      blob = new Blob([textContent], { type: file.type });
    } else {
      blob = base64ToBlob(file.content, file.type);
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
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
  const copyButton = createButton("copy-text-btn", `<i class="bi bi-clipboard"></i> Copy`);
  copyButton.classList.add("btn", "btn-secondary");
  copyButton.addEventListener('click', () => {
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
    const fileType = file.type.split('/')[0].toUpperCase();
    const fileSizeKB = (file.content.length * (3 / 4) / 1024).toFixed(2);
    fileInfoSpan.textContent = `${fileType} · ${fileSizeKB} KB`;

    fileBoxContent.appendChild(iconFilenameWrapper);
    fileBoxContent.appendChild(fileInfoSpan);
  }
  fileBoxContent.addEventListener('click', function (event) {
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
    if (intervalType === "minute" && intervalInt > 0) displayText += ` every <span class="fn-argv">${intervalInt}</span> <span class="fn-argk">minute(s)</span>`;
    else if (intervalType === "hour" && intervalInt > 0) displayText += ` every <span class="fn-argv">${intervalInt}</span> <span class="fn-argk">hour(s)</span>`;
    else if (intervalType === "day") {
      if (specificTime) displayText += ` every day at <span class="fn-argv">${specificTime}</span>`;
      else if (intervalInt > 0) displayText += ` every <span class="fn-argv">${intervalInt}</span> <span class="fn-argk">day(s)</span>`;
    } else if (intervalType === "week" && intervalList && intervalList.length > 0) {
      const days = intervalList.join(", ");
      displayText += ` every <span class="fn-argv">${days}</span> at <span class="fn-argv">${specificTime}</span>`;
    }
    // No response needed inline for CreateReminder
  } else if (name === "CancelReminder") {
    const reminderId = args.reminder_id;
    const foreverOrNext = args.forever_or_next;
    displayText = `<span class="fn-name">CancelReminder</span>`;
    if (foreverOrNext === "forever") displayText += ` of ID <span class="fn-argv">${reminderId}</span> <span class="fn-argk">forever</span>`;
    else if (foreverOrNext === "next") displayText += ` Next Run of ID <span class="fn-argv">${reminderId}</span>`;
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
        if (startTime && endTime) displayText += ` from <span class="fn-argv">${startTime}</span> to <span class="fn-argv">${endTime}</span>`;
        else if (startTime) displayText += ` at <span class="fn-argv">${startTime}</span>`;
      } else {
        displayText += ` from <span class="fn-argv">${startDate}</span>`;
        if (startTime) displayText += ` at <span class="fn-argv">${startTime}</span>`;
        if (endDate) {
          displayText += ` to <span class="fn-argv">${endDate}</span>`;
          if (endTime) displayText += ` until <span class="fn-argv">${endTime}</span>`;
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
    if (title) displayText += `, <span class="fn-argk">title</span> to <span class="fn-argv">\`${title}\`</span>`;
    if (startDate) {
      if (startDate === endDate) {
        displayText += ` on <span class="fn-argv">${startDate}</span>`;
        if (startTime && endTime) displayText += ` from <span class="fn-argv">${startTime}</span> to <span class="fn-argv">${endTime}</span>`;
        else if (startTime) displayText += ` at <span class="fn-argv">${startTime}</span>`;
      } else {
        displayText += ` from <span class="fn-argv">${startDate}</span>`;
        if (startTime) displayText += ` at <span class="fn-argv">${startTime}</span>`;
        if (endDate) {
          displayText += ` to <span class="fn-argv">${endDate}</span>`;
          if (endTime) displayText += ` until <span class="fn-argv">${endTime}</span>`;
        }
      }
    }
    if (allDay !== undefined) displayText += ` <span class="fn-argk">allDay</span> to <span class="fn-argv">${allDay}</span>`;
    if (completed !== undefined) displayText += ` <span class="fn-argk">completed</span> to <span class="fn-argv">${completed}</span>`;
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
  } else if (name === "LinkAttachment" || name === "Imagen") {
    return "";
  }
  // --- Default Rendering (Fallback) ---
  else {
    const formattedArgs = Object.entries(args)
      .filter(([key, value]) => value !== null && value !== undefined && value !== "")
      .map(([key, value]) => {
        let displayValue;
        try { displayValue = JSON.stringify(value); }
        catch (e) { displayValue = String(value); }
        return `<span class="fn-arg"><span class="fn-argk">${key}</span>=<span class="fn-argv">${displayValue}</span></span>`;
      })
      .join(', ');
    displayText += formattedArgs ? ` <span class="fn-args"> ${formattedArgs}</span>` : '';
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
  if (functionName.includes("read") || functionName.includes("get") || functionName.includes("fetch")) {
    return "bi bi-file-earmark-text"; // Example icon for reading/fetching files or data
  } else if (functionName.includes("execute") || functionName.includes("run")) {
    return "bi bi-play-btn"; // Example icon for executing commands
  } else if (functionName.includes("create") || functionName.includes("make") || functionName.includes("generate")) {
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

  const fnResponseSpan = document.querySelector(`#fn-call-${functionId} .fn-response`);
  const fnCallBox = document.getElementById(`fn-call-${functionId}`);

  if (fnResponseSpan && fnCallBox) {
    const functionName = fnCallBox.dataset.functionName;
    fnCallBox.classList.remove('fn-call-box-error'); // Remove error class initially

    if (isSuccess) {
      let successText = "";
      if (functionName === "CreateReminder") {
        successText = ` of ID \`${response.output}\``;
        showArrow = false
      } else if (functionName === "RunCommandBackground") {
        successText = ` Process ID: \`${response.output}\``;
      } else if (functionName === "IsProcessRunning") {
        successText = ` Running: <span class="fn-argv">${response.output}</span>`;
      } else if (["FetchWebsite", "GetSTDOut", "ReadFile"].includes(functionName)) {
        // For functions where output might be large, just show success
        // Click handler will display full content
        successText = ` Success`;
      } else if (["CreateTask", "UpdateTask", "CancelReminder", "CreateFile", "RunCommand", "SendSTDIn", "CreateFolder", "DeleteFile", "DeleteFolder", "KillProcess", "WriteFile", "SendControlC"].includes(functionName)) {
        // For simple actions, show success message
        successText = ` Success`;
      } else {
        // Default success display (e.g., for functions not explicitly handled)
        const formattedContent = JSON.stringify(response.output, null, 2);
        successText = `<span><pre class="fn-inline-response-content">${formattedContent}</pre></span>`;
      }
      fnResponseSpan.innerHTML = successText ? `${showArrow ? "<span class=\"fn-arrow\">-></span>" : ""}${successText}` : '';
    } else { // Handle Error
      fnCallBox.classList.add("fn-call-box-clickable"); // Make error box clickable
      fnCallBox.classList.add('fn-call-box-error');
      fnResponseSpan.innerHTML = ''; // Clear response area on error
    }
  } else {
    console.error(`Function call element with ID ${functionId} not found for response update.`);
  }
}

// Add click handler to chat box
document.getElementById("chat-box").addEventListener("click", function (event) {
  const clickableTarget = event.target.closest(".fn-call-box-clickable");
  const errorTarget = event.target.closest(".fn-call-box-error");

  if (clickableTarget && !errorTarget) { // Handle non-error clicks first
    const functionName = clickableTarget.dataset.functionName;
    const functionId = clickableTarget.dataset.functionId;

    if (functionName === "CreateFile") {
      displayCreateFileContent(functionId);
    } else if (functionName === "RunCommand") {
      displayRunCommandOutput(functionId);
    } else if (functionName === "FetchWebsite") {
      displayFetchWebsiteOutput(functionId); // New handler
    } else if (functionName === "GetSTDOut") {
      displayGetSTDOutOutput(functionId); // New handler
    } else if (functionName === "ReadFile") {
      displayReadFileContent(functionId); // New handler
    } else if (functionName === "WriteFile") {
      displayWriteFileContent(functionId); // New handler
    }
    // Add other non-error clickable handlers here if needed

  } else if (errorTarget) { // Handle error clicks
    const functionId = errorTarget.dataset.functionId;
    displayFunctionError(functionId);
  }
});

/**
 * Displays the error of a function call in the right panel.
 * @param {string} functionId - The ID of the function call.
 */
function displayFunctionError(functionId) {
  const msgDiv = document.getElementById(`fn-call-${functionId}`).closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItem = msg.content.find(c => c.function_response && c.function_response.id === functionId);
  if (contentItem && contentItem.function_response) {
    const functionResponse = contentItem.function_response;
    const error = functionResponse.response.error;

    const rightPanel = document.querySelector('.right-panel');
    const attachmentDisplayArea = document.getElementById('attachment-display-area');

    if (rightPanel.classList.contains('d-none')) {
      rightPanel.classList.remove('d-none');
    }

    attachmentDisplayArea.innerHTML = ''; // Clear previous content

    // Display the error message
    const errorContainer = document.createElement('div');
    errorContainer.classList.add('terminal-error');
    errorContainer.textContent = error;
    attachmentDisplayArea.appendChild(errorContainer);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
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
  const msgDiv = document.getElementById(`fn-call-${functionId}`).closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItem = msg.content.find(c => c.function_call && c.function_call.id === functionId);

  if (contentItem && contentItem.function_call) {
    const functionCall = contentItem.function_call;
    const fileContent = functionCall.args.content;
    const filename = functionCall.args.relative_path;

    const rightPanel = document.querySelector('.right-panel');
    const attachmentDisplayArea = document.getElementById('attachment-display-area');

    if (rightPanel.classList.contains('d-none')) {
      rightPanel.classList.remove('d-none');
    }

    attachmentDisplayArea.innerHTML = ''; // Clear previous content

    // Display the file path
    const filePathHeader = document.createElement('h6');
    filePathHeader.textContent = `File Path: ${filename}`;
    attachmentDisplayArea.appendChild(filePathHeader);

    // Create a pre element to display the code with highlighting
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.classList.add('hljs'); // Add hljs class for highlighting
    code.textContent = fileContent;
    pre.appendChild(code);
    attachmentDisplayArea.appendChild(pre);

    // Highlight the code
    hljs.highlightElement(code);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
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
  const msgDiv = document.getElementById(`fn-call-${functionId}`).closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemCall = msg.content.find(c => c.function_call && c.function_call.id === functionId);
  const contentItemResponce = msg.content.find(c => c.function_response && c.function_response.id === functionId);

  if (contentItemCall && contentItemCall.function_call && contentItemResponce && contentItemResponce.function_response) {
    const functionCall = contentItemCall.function_call;
    const functionResponse = contentItemResponce.function_response;
    const command = functionCall.args.command;

    const rightPanel = document.querySelector('.right-panel');
    const attachmentDisplayArea = document.getElementById('attachment-display-area');

    if (rightPanel.classList.contains('d-none')) {
      rightPanel.classList.remove('d-none');
    }

    attachmentDisplayArea.innerHTML = ''; // Clear previous content

    // Display the command
    const commandHeader = document.createElement('div');
    commandHeader.classList.add('terminal-command');
    commandHeader.textContent = `$ ${command}`;
    attachmentDisplayArea.appendChild(commandHeader);

    if (functionResponse.response.output) {
      const output = functionResponse.response.output[0];
      const error = functionResponse.response.output[1];
      const returnCode = functionResponse.response.output[2];

      // Display the output
      const outputContainer = document.createElement('div');
      outputContainer.classList.add('terminal-output');
      outputContainer.textContent = output || '';
      attachmentDisplayArea.appendChild(outputContainer);

      // Display the error
      if (error) {
        const errorContainer = document.createElement('div');
        errorContainer.classList.add('terminal-error');
        errorContainer.textContent = `stderr: ${error}`;
        attachmentDisplayArea.appendChild(errorContainer);
      }

      // Display the return code
      const returnCodeContainer = document.createElement('div');
      returnCodeContainer.classList.add('terminal-return-code');
      returnCodeContainer.textContent = `Return Code: ${returnCode || 0}`;
      attachmentDisplayArea.appendChild(returnCodeContainer);
    } else if (functionResponse.response.error) {
      // Display the error message
      const errorContainer = document.createElement('div');
      errorContainer.classList.add('terminal-error');
      errorContainer.textContent = functionResponse.response.error;
      attachmentDisplayArea.appendChild(errorContainer);
    }

    // Activate the content tab
    const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
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
  const msgDiv = document.getElementById(`fn-call-${functionId}`).closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemResponce = msg.content.find(c => c.function_response && c.function_response.id === functionId);

  if (contentItemResponce && contentItemResponce.function_response && contentItemResponce.function_response.response.output) {
    const output = contentItemResponce.function_response.response.output;

    const rightPanel = document.querySelector('.right-panel');
    const attachmentDisplayArea = document.getElementById('attachment-display-area');

    if (rightPanel.classList.contains('d-none')) {
      rightPanel.classList.remove('d-none');
    }
    attachmentDisplayArea.innerHTML = ''; // Clear previous content

    const outputContainer = document.createElement('div');
    outputContainer.classList.add('text-attachment-panel'); // Use existing style
    outputContainer.textContent = output;
    attachmentDisplayArea.appendChild(outputContainer);

    const copyButton = createCopyButton(output);
    attachmentDisplayArea.appendChild(copyButton);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
    contentTab.show();
  } else {
    console.error(`Function response for FetchWebsite with ID ${functionId} not found or has no output.`);
  }
}

/**
* Displays the output of a GetSTDOut function call in the right panel.
* @param {string} functionId - The ID of the function call.
*/
function displayGetSTDOutOutput(functionId) {
  const msgDiv = document.getElementById(`fn-call-${functionId}`).closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemResponce = msg.content.find(c => c.function_response && c.function_response.id === functionId);

  if (contentItemResponce && contentItemResponce.function_response && contentItemResponce.function_response.response.output) {
    const outputLines = contentItemResponce.function_response.response.output;
    const output = outputLines.join('\n'); // Join lines into a single string

    const rightPanel = document.querySelector('.right-panel');
    const attachmentDisplayArea = document.getElementById('attachment-display-area');

    if (rightPanel.classList.contains('d-none')) {
      rightPanel.classList.remove('d-none');
    }
    attachmentDisplayArea.innerHTML = ''; // Clear previous content

    const outputContainer = document.createElement('div');
    outputContainer.classList.add('terminal-output'); // Use terminal style
    outputContainer.textContent = output;
    attachmentDisplayArea.appendChild(outputContainer);

    const copyButton = createCopyButton(output);
    attachmentDisplayArea.appendChild(copyButton);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
    contentTab.show();
  } else {
    console.error(`Function response for GetSTDOut with ID ${functionId} not found or has no output.`);
  }
}

/**
* Displays the content of a ReadFile function call in the right panel.
* @param {string} functionId - The ID of the function call.
*/
function displayReadFileContent(functionId) {
  const msgDiv = document.getElementById(`fn-call-${functionId}`).closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemCall = msg.content.find(c => c.function_call && c.function_call.id === functionId);
  const contentItemResponce = msg.content.find(c => c.function_response && c.function_response.id === functionId);

  if (contentItemCall && contentItemCall.function_call && contentItemResponce && contentItemResponce.function_response && contentItemResponce.function_response.response.output) {
    const filename = contentItemCall.function_call.args.relative_path;
    const fileContent = contentItemResponce.function_response.response.output;

    const rightPanel = document.querySelector('.right-panel');
    const attachmentDisplayArea = document.getElementById('attachment-display-area');

    if (rightPanel.classList.contains('d-none')) {
      rightPanel.classList.remove('d-none');
    }
    attachmentDisplayArea.innerHTML = ''; // Clear previous content

    const filePathHeader = document.createElement('h6');
    filePathHeader.textContent = `File Path: ${filename}`;
    attachmentDisplayArea.appendChild(filePathHeader);

    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.classList.add('hljs');
    code.textContent = fileContent;
    pre.appendChild(code);
    attachmentDisplayArea.appendChild(pre);
    hljs.highlightElement(code); // Apply highlighting

    const copyButton = createCopyButton(fileContent);
    attachmentDisplayArea.appendChild(copyButton);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
    contentTab.show();
  } else {
    console.error(`Function call or response for ReadFile with ID ${functionId} not found or has no output.`);
  }
}

/**
* Displays the content that was written by a WriteFile function call.
* @param {string} functionId - The ID of the function call.
*/
function displayWriteFileContent(functionId) {
  const msgDiv = document.getElementById(`fn-call-${functionId}`).closest(".message");
  const msg = JSON.parse(msgDiv.dataset.msg);
  const contentItemCall = msg.content.find(c => c.function_call && c.function_call.id === functionId);

  if (contentItemCall && contentItemCall.function_call) {
    const filename = contentItemCall.function_call.args.relative_path;
    const fileContent = contentItemCall.function_call.args.content; // Get content from the call args

    const rightPanel = document.querySelector('.right-panel');
    const attachmentDisplayArea = document.getElementById('attachment-display-area');

    if (rightPanel.classList.contains('d-none')) {
      rightPanel.classList.remove('d-none');
    }
    attachmentDisplayArea.innerHTML = ''; // Clear previous content

    const filePathHeader = document.createElement('h6');
    filePathHeader.textContent = `File Path: ${filename}`;
    attachmentDisplayArea.appendChild(filePathHeader);

    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.classList.add('hljs');
    code.textContent = fileContent;
    pre.appendChild(code);
    attachmentDisplayArea.appendChild(pre);
    hljs.highlightElement(code); // Apply highlighting

    const copyButton = createCopyButton(fileContent);
    attachmentDisplayArea.appendChild(copyButton);

    // Activate the content tab
    const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
    contentTab.show();
  } else {
    console.error(`Function call for WriteFile with ID ${functionId} not found.`);
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
// --- Textarea Helper ---
// --------------------------------------------------------------------------

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
const modelSelect = document.getElementById('model-select');
// const toggleButtons = document.querySelectorAll('.toggle-button');
const autoSelectButton = document.getElementById('autoselect-tool');
const googleSearchButton = document.getElementById('google-search-tool');

// Global variables to store model compatibility information
let toolSupportedModels = [];
let searchGroundingSupportedModels = [];

// ========== MODEL SELECTION ==========

// Fetch available models from the backend
async function fetchModels() {
  try {
    const response = await fetch('/get_models');
    if (!response.ok) {
      throw new Error('Failed to fetch models');
    }
    const models = await response.json();

    // Clear existing options
    modelSelect.innerHTML = '';

    // Add new options based on API response
    models.forEach(model => {
      const option = document.createElement('option');
      option.value = model;
      option.textContent = model;
      modelSelect.appendChild(option);
    });
    const option = document.createElement('option');
    option.value = "auto";
    option.textContent = "auto";
    modelSelect.appendChild(option);

    // Load saved selection after populating options
    loadSelectedModel();
  } catch (error) {
    console.error('Error fetching models:', error);
  }
}

// Fetch model compatibility information from the backend
async function fetchModelCompatibility() {
  try {
    const response = await fetch('/get_model_compatibility');
    if (!response.ok) {
      throw new Error('Failed to fetch model compatibility');
    }
    const compatibility = await response.json();

    // Store compatibility information
    toolSupportedModels = compatibility.toolSupportedModels || [];
    searchGroundingSupportedModels = compatibility.searchGroundingSupportedModels || [];

    // Update tool availability based on current model after compatibility info is loaded
    updateToolAvailability(modelSelect.value);
  } catch (error) {
    console.error('Error fetching model compatibility:', error);
    // Fallback to hardcoded values if fetch fails
    toolSupportedModels = ['Large25', 'Large20', 'Medium20', 'Small20', 'Large15', 'Medium15', 'Small15'];
    searchGroundingSupportedModels = ['Large20', 'Large20', 'Large15', 'Medium20', 'Medium15'];
    updateToolAvailability(modelSelect.value);
  }
}

// Load saved model from local storage
function loadSelectedModel() {
  const savedModel = localStorage.getItem('selectedModel');
  if (savedModel && Array.from(modelSelect.options).some(opt => opt.value === savedModel)) {
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
  localStorage.setItem('selectedModel', model);
  updateModelSelection(model);
}

// Send model selection to the backend
function updateModelSelection(selectedModel) {
  selectedModel = selectedModel ? selectedModel : modelSelect.value
  socket.emit('set_models', selectedModel == "auto" ? null : selectedModel);
}

// Updated function to dynamically check model compatibility with tools
function updateToolAvailability(selectedModel) {
  // First clear any existing disabled or selected states for a fresh start
  const allButtons = document.querySelectorAll('.toggle-button');

  // Special case for 'auto' selection
  if (selectedModel === 'auto') {
    // When auto is selected, check if auto button is selected and update accordingly
    if (autoSelectButton.dataset.state === 'selected') {
      // If Auto is selected, disable all other buttons
      allButtons.forEach(button => {
        if (button.id !== 'autoselect-tool') {
          button.dataset.state = 'disabled';
        }
      });
    } else {
      // If Auto is not selected, enable all buttons
      allButtons.forEach(button => {
        if (button.dataset.state === 'disabled') {
          button.dataset.state = 'unselected';
        }
      });
    }

    saveButtonStates();
    updateToolsSelection();
    return;
  }

  // Check if the selected model supports tools
  const modelSupportsTools = toolSupportedModels.includes(selectedModel);
  const modelSupportsSearch = searchGroundingSupportedModels.includes(selectedModel);

  // Check current button states
  const isAutoSelected = autoSelectButton.dataset.state === 'selected';
  const isGoogleSearchSelected = googleSearchButton && googleSearchButton.dataset.state === 'selected';

  // If Auto is selected, apply its rules regardless of model
  if (isAutoSelected) {
    updateToggleButtonStates('auto');
    return;
  }

  // First, handle the Google Search button
  if (googleSearchButton) {
    if (!modelSupportsSearch) {
      // If currently selected but not supported, unselect it
      if (googleSearchButton.dataset.state === 'selected') {
        googleSearchButton.dataset.state = 'unselected';
      }
      googleSearchButton.dataset.state = 'disabled';
    } else if (googleSearchButton.dataset.state === 'disabled' && modelSupportsSearch) {
      // Re-enable if it was disabled but is now supported
      googleSearchButton.dataset.state = 'unselected';
    }
  }

  // If Google is selected, apply its rules to other buttons
  if (isGoogleSearchSelected && modelSupportsSearch) {
    updateToggleButtonStates('google');
    return;
  }

  // Handle reminder and fetch website buttons
  const otherToolButtons = [
    document.getElementById('reminder-tool'),
    document.getElementById('fetch-website-tool'),
    document.getElementById('imagen-tool'),
    document.getElementById('computer-tool')
  ];

  otherToolButtons.forEach(button => {
    if (button) {
      if (!modelSupportsTools) {
        // If selected but not supported, unselect it
        if (button.dataset.state === 'selected') {
          button.dataset.state = 'unselected';
        }
        button.dataset.state = 'disabled';
      } else if (button.dataset.state === 'disabled' && modelSupportsTools) {
        // Re-enable if it was disabled but is now supported
        button.dataset.state = 'unselected';
      }
    }
  });

  saveButtonStates();
  updateToolsSelection();
}

// Handle model selection
modelSelect.addEventListener('change', function () {
  const selectedModel = this.value;
  saveSelectedModel(selectedModel);
  updateToolAvailability(selectedModel);
});

// ========== TOOLS SELECTION ==========

// Load saved button states from local storage
function loadButtonStates() {
  const allButtons = document.querySelectorAll('.toggle-button');
  allButtons.forEach(button => {
    const savedState = localStorage.getItem(button.id + '-state');
    if (savedState) {
      button.dataset.state = savedState;
    }
  });

  // Apply model compatibility check after loading saved states
  updateToolAvailability(modelSelect.value);
}

// Save button states to local storage
function saveButtonStates() {
  const allButtons = document.querySelectorAll('.toggle-button');
  allButtons.forEach(button => {
    localStorage.setItem(button.id + '-state', button.dataset.state);
  });
}

// Update toggle button states based on Auto or Google Search selection
function updateToggleButtonStates(selectedTool) {
  const allButtons = document.querySelectorAll('.toggle-button');

  allButtons.forEach(button => {
    if (selectedTool === 'auto') {
      // If Auto is selected, disable all other buttons
      if (button.id !== 'autoselect-tool') {
        button.dataset.state = 'disabled';
      }
    } else if (selectedTool === 'google') {
      // If Google Search is selected, disable Reminder and Fetch
      if (button.id === 'reminder-tool' || button.id === 'fetch-website-tool' || button.id === 'imagen-tool' || button.id === 'computer-tool') {
        button.dataset.state = 'disabled';
      } else if (button.id !== 'autoselect-tool' && button.id !== 'google-search-tool') {
        // For any other buttons besides Auto and Google, set to unselected if they were disabled
        if (button.dataset.state === 'disabled') {
          button.dataset.state = 'unselected';
        }
      }
    } else {
      // No tool is selected, enable all buttons (or keep their state)
      // Only change state if the button was previously disabled
      if (button.dataset.state === 'disabled') {
        button.dataset.state = 'unselected';
      }
    }
  });

  saveButtonStates();
  updateToolsSelection();
}

// Send tools selection to the backend
function updateToolsSelection() {
  const isAutoSelected = autoSelectButton.dataset.state === 'selected';

  if (isAutoSelected) {
    // If Auto is selected, send null to use default behavior
    socket.emit('set_tools', null);
  } else {
    // Get all selected tools
    const selectedTools = [];
    const allButtons = document.querySelectorAll('.toggle-button:not(#autoselect-tool)');

    allButtons.forEach(button => {
      if (button.dataset.state === 'selected') {
        // Convert button ID to tool name format
        const buttonId = button.id.replace('-tool', '');
        let toolName;

        // Map button IDs to tool names
        if (buttonId === 'google-search') {
          toolName = 'SearchGrounding';
        } else if (buttonId === 'reminder') {
          toolName = 'Reminder';
        } else if (buttonId === 'fetch-website') {
          toolName = 'FetchWebsite';
        } else if (buttonId === 'computer') {
          toolName = 'ComputerTool';
        } else {
          // Use capitalized version of the ID for other tools
          toolName = buttonId.split('-').map(word =>
            word.charAt(0).toUpperCase() + word.slice(1)
          ).join('');
        }

        selectedTools.push(toolName);
      }
    });
    socket.emit('set_tools', selectedTools.length > 0 ? selectedTools : []);
  }
}

// Set up Auto button click handler
autoSelectButton.addEventListener('click', function () {
  if (this.dataset.state === 'disabled') {
    return; // Don't do anything if the button is disabled
  }

  const isBeingSelected = this.dataset.state === 'unselected';
  this.dataset.state = isBeingSelected ? 'selected' : 'unselected';

  if (isBeingSelected) {
    // If Auto is being turned ON, disable all other buttons
    updateToggleButtonStates('auto');
  } else {
    // If Auto is being turned OFF, apply model compatibility
    updateToolAvailability(modelSelect.value);
  }
});

// Set up Google Search button click handler
googleSearchButton.addEventListener('click', function () {
  if (this.dataset.state === 'disabled') {
    return; // Don't do anything if the button is disabled
  }

  // If Auto is selected, clicking any other button should do nothing
  if (autoSelectButton.dataset.state === 'selected') {
    return;
  }

  const isBeingSelected = this.dataset.state === 'unselected';
  this.dataset.state = isBeingSelected ? 'selected' : 'unselected';

  if (isBeingSelected) {
    // If Google Search is being turned ON, apply its rules to other buttons
    updateToggleButtonStates('google');
  } else {
    // If Google Search is being turned OFF, restore compatibility based on model
    updateToolAvailability(modelSelect.value);
  }
});

// Initialize listeners for all buttons
function initializeButtonListeners() {
  // Remove any existing listeners first to avoid duplicates
  const allButtons = document.querySelectorAll('.toggle-button:not(#autoselect-tool):not(#google-search-tool)');

  allButtons.forEach(button => {
    // Clone the button to remove all event listeners
    const newButton = button.cloneNode(true);
    button.parentNode.replaceChild(newButton, button);

    // Add new event listener
    newButton.addEventListener('click', function () {
      if (this.dataset.state === 'disabled') {
        return; // Don't do anything if the button is disabled
      }

      // If Auto is selected or Google is selected, clicking other buttons should do nothing
      if (autoSelectButton.dataset.state === 'selected' ||
        (googleSearchButton.dataset.state === 'selected' &&
          (this.id === 'reminder-tool' || this.id === 'fetch-website-tool' || this.id === 'imagen-tool' || this.id === 'computer-tool'))) {
        return;
      }

      this.dataset.state = (this.dataset.state === 'unselected') ? 'selected' : 'unselected';
      saveButtonStates();
      updateToolsSelection();
    });
  });
}

// Initialize everything when the page loads
document.addEventListener('DOMContentLoaded', function () {
  fetchModels();
  fetchModelCompatibility();

  // Initialize button listeners after a short delay to ensure DOM is ready
  setTimeout(initializeButtonListeners, 500);
});

// Function to calculate and set the max-height of scrollable areas
function setScrollableAreaMaxHeight() {
  const rightPanelTabs = document.getElementById('rightPanelTabs');
  const attachmentDisplayArea = document.getElementById('attachment-display-area');
  const notificationDisplayArea = document.getElementById('notification-display-area');

  if (!rightPanelTabs || !attachmentDisplayArea || !notificationDisplayArea) {
    return; // Exit if elements are not found
  }

  const tabsHeight = rightPanelTabs.offsetHeight;
  const availableHeight = window.innerHeight - tabsHeight - 22; // 20 is for margin

  attachmentDisplayArea.style.maxHeight = `${availableHeight}px`;
  notificationDisplayArea.style.maxHeight = `${availableHeight}px`;
}

// Call the function on page load and window resize
document.addEventListener('DOMContentLoaded', setScrollableAreaMaxHeight);
window.addEventListener('resize', setScrollableAreaMaxHeight);

// ==========================================================================
// --- Socket Communication ---
// ==========================================================================

/**
 * Sends a message with or without file attachments.
 */
const sendMessage = async () => {
  const input = document.getElementById("message-input");
  const message = input.value;

  const filesData = [];

  for (let i = 0; i < fileContents.length; i++) {
    const fileData = fileContents[i];
    fileId = generateUUID();
    await uploadFileInChunks(fileData.content, fileData.name, fileId);
    filesData.push({
      filename: fileData.name,
      type: fileData.type,
      id: fileId,
    });
  }

  input.value = "";
  fileContents = [];
  displayFileNames();
  updateTextareaRows();

  socket.emit("send_message", { message: message, files: filesData });
};

// --------------------------------------------------------------------------
// --- Socket Event Handlers ---
// --------------------------------------------------------------------------

socket.on("connect", () => {
  socket.emit("get_chat_history");
  updateModelSelection()
  updateToolsSelection();
});

socket.on("chat_update", updateChatDisplay);
socket.on("updated_msg", updateMessageInChatBox);
socket.on("add_message", addMessageToChatBox);
socket.on("delete_message", deleteMessage);

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
    "justify-content-end", /* Align buttons to the right */
    "mt-2",
    "p-1" /* Reduced padding */
  );

  // 3. Create the message text, Agree button, and Deny button
  const messageText = document.createElement("span"); /* Use span for inline display */
  messageText.textContent = msg; // Or msg.content if it's an object
  messageText.classList.add("me-2", "text-muted"); /* Muted text color, margin right */
  permissionRequestDiv.appendChild(messageText);

  const agreeButton = document.createElement("button");
  agreeButton.textContent = "Agree";
  agreeButton.classList.add("btn", "btn-sm", "toggle-button"); /* Use toggle-button style */
  agreeButton.addEventListener("click", () => {
    socket.emit("set_permission", true);
    permissionRequestDiv.remove();
  });
  permissionRequestDiv.appendChild(agreeButton);

  const denyButton = document.createElement("button");
  denyButton.textContent = "Deny";
  denyButton.classList.add("btn", "btn-sm", "toggle-button"); /* Use toggle-button style */
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

document.addEventListener('DOMContentLoaded', function () {
  // Create a resizer element
  const resizer = document.createElement('div');
  resizer.className = 'panel-resizer';
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
  resizer.addEventListener('mouseover', () => {
    resizer.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
  });

  resizer.addEventListener('mouseout', () => {
    resizer.style.backgroundColor = 'transparent';
  });

  // Get panel elements
  const rightPanel = document.querySelector('.right-panel');
  const chatContainer = document.querySelector('.chat-container');

  // Add the resizer to the right panel
  rightPanel.style.position = 'relative';
  rightPanel.prepend(resizer);

  // Variables for tracking the resize
  let isResizing = false;
  let lastDownX = 0;
  let panelWasHidden = false; // Track if the panel was hidden

  // Function to start resizing from the right edge
  function startResizeFromEdge(e) {
    if (rightPanel.classList.contains('d-none')) {
      isResizing = true;
      lastDownX = e.clientX;
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      panelWasHidden = true; // Indicate that the panel was hidden
      e.preventDefault(); // Prevent text selection during drag
    }
  }

  // Add event listeners for resizing
  resizer.addEventListener('mousedown', (e) => {
    isResizing = true;
    lastDownX = e.clientX; // Store the initial mouse position
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
    panelWasHidden = rightPanel.classList.contains('d-none'); // Check if panel was hidden
  });

  // Add mousedown listener to chatContainer for dragging from the right edge
  chatContainer.addEventListener('mousedown', (e) => {
    // Check if the mouse is near the right edge
    if (e.clientX > chatContainer.offsetWidth - 10 && !isResizing) { // Adjust the 10 value for sensitivity
      startResizeFromEdge(e);
    }
  });

  document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;

    const containerWidth = document.querySelector('.container-fluid').offsetWidth;
    let rightPanelWidth;
    let chatContainerWidth;

    if (panelWasHidden) {
      // Dragging to show the panel
      rightPanel.classList.remove('d-none');
      rightPanel.classList.add('col-md-4');
      chatContainer.classList.remove('col-md-12');
      chatContainer.classList.add('col-md-8');

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
    const containerWidth = document.querySelector('.container-fluid').offsetWidth;
    const rightPanelWidth = rightPanel.offsetWidth;
    const paddingLeft = parseFloat(window.getComputedStyle(rightPanel).paddingLeft);
    const paddingRight = parseFloat(window.getComputedStyle(rightPanel).paddingRight);
    const contentWidth = rightPanelWidth - paddingLeft - paddingRight;
    const rightPanelPercent = (contentWidth / containerWidth) * 100;
    localStorage.setItem('rightPanelWidth', rightPanelPercent.toString());
  }

  // Function to load the right panel width from local storage
  function loadRightPanelWidth() {
    const savedWidth = localStorage.getItem('rightPanelWidth');
    if (savedWidth) {
      const rightPanelPercent = parseFloat(savedWidth) ? parseFloat(savedWidth) : 0.1;
      rightPanel.style.width = `${rightPanelPercent}%`;
      chatContainer.style.width = `${100 - rightPanelPercent}%`;
    }
  }

  // Call loadRightPanelWidth on page load
  loadRightPanelWidth();

  document.addEventListener('mouseup', () => {
    if (isResizing) {
      isResizing = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      panelWasHidden = false; // Reset the flag

      // Save the right panel width when resizing stops
      saveRightPanelWidth();
    }
  });
  // Initialize Bootstrap Tabs explicitly
  var tabElList = [].slice.call(document.querySelectorAll('#rightPanelTabs button'))
  tabElList.forEach(tabEl => {
    new bootstrap.Tab(tabEl)
  })
  // Save initial width on load in case the user doesn't resize
  window.addEventListener('beforeunload', saveRightPanelWidth);
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

document.addEventListener('DOMContentLoaded', function () {
  fetchModels();
  fetchModelCompatibility();

  // Initialize button listeners after a short delay to ensure DOM is ready
  setTimeout(initializeButtonListeners, 500);

  // Request existing notifications on page load
  socket.emit("get_notifications");
});

// --- Key State Object ---
const keyState = {};

document.addEventListener('keydown', function (event) {
  // --- Check if the focus is on a textarea or input type="text" ---
  const activeElement = document.activeElement;
  if (activeElement && (activeElement.tagName === 'TEXTAREA' || (activeElement.tagName === 'INPUT' && activeElement.type === 'text'))) {
    return; // Ignore the key press if focus is on a textarea or text input
  }

  // --- Update Key State ---
  keyState[event.code] = true;

  // --- Right Panel Resize Shortcuts (R + number) ---
  if (keyState['KeyR']) {
    if (keyState['Digit1']) {
      resizeRightPanel(10);
    } else if (keyState['Digit2']) {
      resizeRightPanel(20);
    } else if (keyState['Digit3']) {
      resizeRightPanel(30);
    } else if (keyState['Digit4']) {
      resizeRightPanel(40);
    } else if (keyState['Digit5']) {
      resizeRightPanel(50);
    } else if (keyState['Digit6']) {
      resizeRightPanel(60);
    } else if (keyState['Digit7']) {
      resizeRightPanel(70);
    } else if (keyState['Digit8']) {
      resizeRightPanel(80);
    } else if (keyState['Digit9']) {
      resizeRightPanel(90);
    } else if (keyState['Digit0']) {
      resizeRightPanel(0.1);
    }
    return
  }

  // --- Toggle Tools Shortcuts (t + number) ---
  if (keyState['KeyT'] && !event.ctrlKey) {
    if (event.code === 'Digit1') {
      googleSearchButton.click();
    }
    else if (event.code === 'Digit2') {
      const scheduleButton = document.getElementById('reminder-tool');
      scheduleButton.click();
    }
    else if (event.code === 'Digit3') {
      const fetchWebsiteButton = document.getElementById('fetch-website-tool');
      fetchWebsiteButton.click();
    }
    else if (event.code === 'Digit4') {
      const fetchWebsiteButton = document.getElementById('imagen-tool');
      fetchWebsiteButton.click();
    }
    else if (event.code === 'Digit5') {
      const computerToolButton = document.getElementById('computer-tool');
      computerToolButton.click();
    }
    return
  }
  if (keyState['KeyA'] && !event.ctrlKey) {
    autoSelectButton.click();
    return
  }

  // --- Toggle Tabs Shortcuts (c, N, S) ---
  if (keyState['KeyC'] && !event.ctrlKey) {
    // Toggle Content tab
    const contentTab = new bootstrap.Tab(document.getElementById('content-tab'));
    contentTab.show();
    return
  } else if (keyState['KeyN'] && !event.ctrlKey) {
    // Toggle Notification tab
    const notificationTab = new bootstrap.Tab(document.getElementById('notification-tab'));
    notificationTab.show();
    return
  } else if (event.ctrlKey && event.key === 's' && event.code === 'KeyS') {
    showShortcutsPopup();
    event.preventDefault(); // Prevent the browser from saving the page
    return
  } else if (keyState['KeyS']) {
    // Toggle Schedule tab
    const scheduleTab = new bootstrap.Tab(document.getElementById('schedule-tab'));
    scheduleTab.show();
    return
  }

  // --- Enter Prompt Shortcut (/) ---
  if (event.key === '/' && event.code === 'Slash') {
    // Focus on the message input
    document.getElementById('message-input').focus();
    event.preventDefault(); // Prevent the slash from being entered in the input
    return
  }
  if (event.key === 'd' && event.code === 'KeyD') {
    // Focus on the message input
    document.getElementById('new-task').focus();
    event.preventDefault(); // Prevent the D from being entered in the input
    return
  }
  // --- Select Model Shortcuts (m + number) ---
  if (keyState['KeyM']) {
    const modelSelect = document.getElementById("model-select");
    if (modelSelect) {
      if (keyState['Digit1']) {
        selectModelByIndex(modelSelect, 0);
      } else if (keyState['Digit2']) {
        selectModelByIndex(modelSelect, 1);
      } else if (keyState['Digit3']) {
        selectModelByIndex(modelSelect, 2);
      } else if (keyState['Digit4']) {
        selectModelByIndex(modelSelect, 3);
      } else if (keyState['Digit5']) {
        selectModelByIndex(modelSelect, 4);
      } else if (keyState['Digit6']) {
        selectModelByIndex(modelSelect, 5);
      } else if (keyState['Digit7']) {
        selectModelByIndex(modelSelect, 6);
      } else if (keyState['Digit8']) {
        selectModelByIndex(modelSelect, 7);
      }
    }
    return
  }
  // --- Close Shortcuts Popup (Esc) ---
  if (event.key === 'Escape' || event.code === 'Escape') {
    const popup = document.querySelector('.shortcuts-popup');
    if (popup) {
      popup.remove();
      document.body.style.overflow = 'auto'; // Restore scrolling
    }
    return
  }
});

document.addEventListener('keyup', function (event) {
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
  const rightPanel = document.querySelector('.right-panel');
  const chatContainer = document.querySelector('.chat-container');
  const containerWidth = document.querySelector('.container-fluid').offsetWidth;

  const rightPanelWidth = (percentage / 100) * containerWidth;
  const chatContainerWidth = containerWidth - rightPanelWidth;

  rightPanel.style.width = `${percentage}%`;
  chatContainer.style.width = `${100 - percentage}%`;

  // Save the right panel width to local storage
  localStorage.setItem('rightPanelWidth', percentage.toString());
}

/**
 * Selects the option at the specified index in the select element.
 * @param {HTMLSelectElement} selectElement - The select element.
 * @param {number} index - The index of the option to select.
 */
function selectModelByIndex(selectElement, index) {
  if (selectElement && selectElement.options && index >= 0 && index < selectElement.options.length) {
    selectElement.selectedIndex = index;
    // Dispatch a change event to trigger any associated actions
    selectElement.dispatchEvent(new Event('change'));
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
    "`s`: Toggle Schedule tab",
    "`/`: Focus on message input",
    "`m + [1-8]`: Select model by index",
    "`Ctrl + S`: Show shortcuts popup"
  ];

  const popupContent = shortcuts.map(shortcut => marked.parse(shortcut)).join('');

  // Create the popup element
  const popup = document.createElement('div');
  popup.classList.add('shortcuts-popup');
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
  const closeButton = popup.querySelector('.close-popup-button');
  closeButton.addEventListener('click', function () {
    popup.remove();
  });

  // Prevent scrolling of the main page when the popup is open
  document.body.style.overflow = 'hidden';

  // Restore scrolling when the popup is closed
  popup.addEventListener('transitionend', function () {
    if (!document.body.contains(popup)) {
      document.body.style.overflow = 'auto';
    }
  });
}
