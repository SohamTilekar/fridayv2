// main.js

// --- Global Variables ---
let fileContents = []; // Global variable to store file information (name and content)
let videoId = null; // Unique ID for the video being uploaded
const CHUNK_SIZE = 1024 * 1024; // 1MB chunks
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
const uploadVideoInChunks = async (base64Video, filename, videoId) => {
  const totalChunks = Math.ceil(base64Video.length / CHUNK_SIZE);

  socket.emit("start_upload_video", videoId);

  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, base64Video.length);
    const chunk = base64Video.substring(start, end);

    socket.emit("upload_video_chunck", {
      id: videoId,
      chunck: chunk,
      idx: i,
      filename: filename,
    });
  }

  socket.emit("end_upload_video", videoId);
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
  // Clear previous content (important for updates)
  msgDiv.innerHTML = msg.content.length
    ? ""
    : `<div class="thinking-loader">
         <div class="dot"></div>
         <div class="dot"></div>
         <div class="dot"></div>
     </div>`;

  const attachmentDiv = document.createElement("div");
  attachmentDiv.classList.add("attachments");
  attachmentDiv.innerHTML = "<strong>Attachments:</strong><br>";

  // Render each Content item separately
  msg.content.forEach((contentItem) => {
    const contentDiv = document.createElement("div");
    contentDiv.classList.add("message-content");

    let contentHtml = "";
    if (contentItem.text && contentItem.text.trim() !== "") {
      let textContent = contentItem.text;
      if (contentItem.grounding_metadata) {
        textContent = applyGroundingInfo(
          textContent,
          contentItem.grounding_metadata,
        );
      }
      contentHtml = marked.parse(textContent);
      if (contentItem.processing) {
        contentHtml = `
                  ${contentHtml}
                  <div class="thinking-loader">
                      <div class="dot"></div>
                      <div class="dot"></div>
                      <div class="dot"></div>
                  </div>
              `;
      }
    } else if (contentItem.text) {
      contentHtml = `
              <div class="thinking-loader">
                  <div class="dot"></div>
                  <div class="dot"></div>
                  <div class="dot"></div>
              </div>
          `;
    } else if (contentItem.attachment && msg.role == "user") {
      displayAttachments(attachmentDiv, contentItem.attachment);
    }
    contentDiv.innerHTML = contentHtml;
    msgDiv.appendChild(contentDiv);

    // Enhance code blocks/inlines
    enhanceCodeBlocks(contentDiv);
    enhanceCodeInlines(contentDiv);
    initializeTooltips(contentDiv);
  });

  if (attachmentDiv.innerHTML != "<strong>Attachments:</strong><br>")
    msgDiv.appendChild(attachmentDiv);
}

/**
 * Creates the standard message controls (copy, delete, timestamp).
 */
function createMessageControls(msg) {
  const controlsDiv = document.createElement("div"); // Create a container for the controls

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

const addMessageToChatBox = handleChatBoxUpdate((msg, appendAtTop = false) => {
  const chatBox = document.getElementById("chat-box");
  const msgDiv = document.createElement("div");
  msgDiv.classList.add("message", msg.role === "user" ? "user-msg" : "ai-msg");
  msgDiv.id = msg.id;

  renderMessageContent(msgDiv, msg); // Render the message content

  const controlsDiv = createMessageControls(msg); // Create the controls
  msgDiv.appendChild(controlsDiv);

  if (appendAtTop) {
    chatBox.prepend(msgDiv);
  } else {
    chatBox.appendChild(msgDiv);
  }
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
      copyToClipboard(codeBlock.innerText, copyButton),
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
    result =
      result.substring(0, idx) +
      `<i class="bi bi-info-circle grounding-marker" data-tooltip="${encodeURIComponent(marked.parse(tooltipContent))}"></i>` +
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

/**
 * Creates an element to display attachments.
 */
function createAttachmentElement(file) {
  if (file.type.startsWith("image/")) {
    const img = document.createElement("img");
    img.src = `data:${file.type};base64,${file.content}`;
    img.alt = file.filename;
    img.style.maxWidth = "50px";
    img.style.maxHeight = "50px";
    img.style.display = "block";
    return img;
  } else if (file.type.startsWith("video/")) {
    const video = document.createElement("video");
    video.alt = file.name;
    video.style.maxWidth = "50px";
    video.style.maxHeight = "50px";
    video.style.marginRight = "5px";
    video.controls = false;
    video.muted = true;
    video.autoplay = true;
    video.loop = true;
    video.src = `data:${file.type};base64,${file.content}`;
    video.type = file.type;
    video.play();
    return video;
  } else {
    const fileLink = document.createElement("a");
    fileLink.href = `data:${file.type};base64,${file.content}`;
    fileLink.download = file.filename;
    fileLink.textContent = file.filename;
    return fileLink;
  }
}

/**
 * Displays the attached files in the chat.
 */
function displayAttachments(attachmentDiv, file) {
  const attachmentElement = createAttachmentElement(file);
  attachmentDiv.appendChild(attachmentElement);
  attachmentDiv.appendChild(document.createElement("br"));
}

// --------------------------------------------------------------------------
// --- File Handling UI ---
// --------------------------------------------------------------------------

/**
 * Displays file names in boxes with delete buttons.
 */
function displayFileNames() {
  const displayArea = document.getElementById("file-display-area");
  displayArea.innerHTML = "";
  displayArea.style.display = "flex";
  displayArea.style.flexWrap = "wrap";

  fileContents.forEach((fileData, index) => {
    const fileBox = document.createElement("div");
    fileBox.classList.add("file-box");

    let fileDisplayElement;
    if (fileData.type.startsWith("image/")) {
      fileDisplayElement = createAttachmentElement(fileData);
    } else if (fileData.type.startsWith("video/")) {
      fileDisplayElement = createAttachmentElement(fileData);
    } else {
      const fileNameSpan = document.createElement("span");
      fileNameSpan.textContent = fileData.name;
      fileDisplayElement = fileNameSpan;
    }
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
    if (fileData.type.startsWith("video/")) {
      videoId = generateUUID();
      await uploadVideoInChunks(fileData.content, fileData.name, videoId);
      filesData.push({
        filename: fileData.name,
        type: fileData.type,
        id: videoId,
      });
    } else {
      try {
        let base64Content = fileData.content;
        filesData.push({
          filename: fileData.name,
          content: base64Content,
          type: fileData.type,
        });
      } catch (error) {
        console.error("Error processing file:", error);
        addMessageToChatBox(document.getElementById("chat-box"), {
          role: "model",
          content: [
            {
              text: `Error processing file ${fileData.name}: ${error.message}`,
            },
          ],
          id: Date.now().toString(36),
        });
        return;
      }
    }
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
});

socket.on("chat_update", updateChatDisplay);
socket.on("updated_msg", updateMessageInChatBox);
socket.on("add_message", addMessageToChatBox);
socket.on("delete_message", deleteMessage);

// --------------------------------------------------------------------------
// --- Right Panel Functions ---
// --------------------------------------------------------------------------

function toggleRightPanel() {
  const panel = document.getElementById("rightPanel");
  panel.classList.toggle("show");
}

function shrinkChat() {
  socket.emit("srink_chat");
}

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
            type: file.type,
            content: content,
          });
        } catch (error) {
          console.error("Error reading file:", error);
          fileContents.push({
            name: file.name,
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
      const language = lang && hljs.getLanguage(lang) ? lang : null;
      if (language !== null) return hljs.highlight(code, { language }).value;
      else return hljs.highlightAuto(code).value;
    },
  }),
);
