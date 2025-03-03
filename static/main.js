// main.js

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

// --- Helper Functions ---

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

// --- Code Block Enhancement Functions ---

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
      result.slice(0, insertIndex - 1) +
      groundingMetadata.rendered_content +
      result.slice(insertIndex);
  }

  return result;
}

/**
 * Initializes tooltips for grounding markers.
 */
function initializeTooltips() {
  document.querySelectorAll(".grounding-marker").forEach((marker) => {
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

// --- Attachment Display Function ---

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
function displayAttachments(msgDiv, attachments) {
  if (attachments && attachments.length > 0) {
    const attachmentsDiv = document.createElement("div");
    attachmentsDiv.classList.add("attachments");
    attachmentsDiv.innerHTML = "<strong>Attachments:</strong><br>";

    attachments.forEach((file) => {
      const attachmentElement = createAttachmentElement(file);
      attachmentsDiv.appendChild(attachmentElement);
      attachmentsDiv.appendChild(document.createElement("br"));
    });

    msgDiv.appendChild(attachmentsDiv);
  }
}

// --- Message Handling Functions ---

/**
 * Adds a message to the chat box.
 */
function addMessageToChatBox(chatBox, msg) {
  const msgDiv = document.createElement("div");
  msgDiv.classList.add("message", msg.role === "user" ? "user-msg" : "ai-msg");
  msgDiv.id = msg.id;

  let messageContent = "";
  if (msg.content && msg.content.startsWith("Processing ")) {
    messageContent = `
      ${msg.content}
      <div class="thinking-loader">
        <div class="dot"></div>
        <div class="dot"></div>
        <div class="dot"></div>
      </div>
    `;
  } else if (msg.content !== "") {
    // Apply grounding information before parsing with marked
    let contentWithGrounding = msg.content;
    if (msg.grounding_metadata) {
      contentWithGrounding = applyGroundingInfo(
        msg.content,
        msg.grounding_metadata,
      );
    }
    messageContent = marked.parse(contentWithGrounding);
  } else {
    messageContent = `
      <div class="thinking-loader">
        <div class="dot"></div>
        <div class="dot"></div>
        <div class="dot"></div>
      </div>
    `;
  }
  msgDiv.innerHTML = messageContent;

  const copyButton = createButton(
    "copy-msg-btn",
    `<i class="bi bi-clipboard"></i> Copy`,
  );
  copyButton.addEventListener("click", () =>
    copyToClipboard(msg.content, copyButton),
  );
  msgDiv.appendChild(copyButton);

  const deleteButton = createButton(
    "delete-msg-btn",
    `<i class="bi bi-trash-fill"></i> Delete`,
  );
  deleteButton.addEventListener("click", () => deleteMessage(msg.id));

  const timestampSpan = document.createElement("span");
  timestampSpan.classList.add("timestamp");
  const timestamp = new Date(msg.time_stamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  timestampSpan.textContent = timestamp;

  msgDiv.appendChild(deleteButton);
  msgDiv.appendChild(timestampSpan);

  displayAttachments(msgDiv, msg.attachments);

  chatBox.appendChild(msgDiv);
  chatBox.scrollTop = chatBox.scrollHeight;

  // Initialize tooltips after adding to DOM
  initializeTooltips();
}

/**
 * Deletes a message from the server and updates the chat.
 */
function deleteMessage(messageId) {
  socket.emit("delete_message", { message_id: messageId });
}

/**
 * Updates a message in the chat box.
 */
function updateMessageInChatBox(msg) {
  const msgDiv = document.getElementById(msg.id);

  // Apply grounding information before parsing with marked
  let contentWithGrounding = msg.content;
  if (msg.grounding_metadata) {
    contentWithGrounding = applyGroundingInfo(
      msg.content,
      msg.grounding_metadata,
    );
  }
  msgDiv.innerHTML = marked.parse(contentWithGrounding);

  const copyButton = createButton(
    "copy-msg-btn",
    `<i class="bi bi-clipboard"></i> Copy`,
  );
  copyButton.addEventListener("click", () =>
    copyToClipboard(msg.content, copyButton),
  );
  msgDiv.appendChild(copyButton);

  const deleteButton = createButton(
    "delete-msg-btn",
    `<i class="bi bi-trash-fill"></i> Delete`,
  );
  deleteButton.addEventListener("click", () => deleteMessage(msg.id));

  const timestampSpan = document.createElement("span");
  timestampSpan.classList.add("timestamp");
  const timestamp = new Date(msg.time_stamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  timestampSpan.textContent = timestamp;

  msgDiv.appendChild(deleteButton);
  msgDiv.appendChild(timestampSpan);

  displayAttachments(msgDiv, msg.attachments);

  enhanceCodeBlocks(msgDiv);
  enhanceCodeInlines(msgDiv);

  // Initialize tooltips after updating
  initializeTooltips();
}

/**
 * Updates the entire chat display with the given history.
 */
function updateChatDisplay(history) {
  const chatBox = document.getElementById("chat-box");
  chatBox.innerHTML = "";
  history.forEach((msg) => addMessageToChatBox(chatBox, msg));

  chatBox.scrollTop = chatBox.scrollHeight;
  enhanceCodeBlocks(chatBox);
  enhanceCodeInlines(chatBox);

  // Initialize tooltips after updating entire chat
  initializeTooltips();
}

// --- File Handling Functions ---

// Global variable to store file information (name and content)
let fileContents = [];

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

// --- Socket Event Handling ---
const socket = io();

/**
 * Initializes the chat by fetching the chat history from the server.
 */
function initializeChat() {
  socket.emit("get_chat_history");
}

socket.on("connect", () => {
  socket.emit("get_chat_history");
});

socket.on("chat_update", updateChatDisplay);
socket.on("updated_msg", updateMessageInChatBox);

// --- Video Upload Constants and Functions ---
const CHUNK_SIZE = 1024 * 1024; // 1MB chunks
let videoId = null; // Unique ID for the video being uploaded

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
          role: "ai",
          content: `Error processing file ${fileData.name}: ${error.message}`,
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

// --- Textarea Helper Functions ---

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

// --- Event Listener Functions ---
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
          role: "ai",
          content: `File ${file.name} is not a supported text or image file.`,
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

// --- Event Listeners ---
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

// --- Initialization ---
initializeChat();
