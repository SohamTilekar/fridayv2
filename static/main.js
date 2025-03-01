// Initialize Marked with Highlight.js
const { Marked } = globalThis.marked;
const { markedHighlight } = globalThis.markedHighlight;

const marked = new Marked(
  markedHighlight({
    emptyLangClass: "hljs",
    langPrefix: "hljs language-",
    highlight(code, lang, info) {
      let highlightedCode;

      if (lang && hljs.getLanguage(lang)) {
        highlightedCode = hljs.highlight(code, { language: lang }).value;
      } else {
        highlightedCode = hljs.highlight(code, { language: "plaintext" }).value;
      }

      return highlightedCode;
    },
  }),
);
// --- Helper Functions ---
/**
 * Creates a button element with the given class and inner HTML.
 * @param {string} className - The class name for the button.
 * @param {string} innerHTML - The inner HTML for the button.
 * @returns {HTMLButtonElement} - The created button element.
 */
function createButton(className, innerHTML) {
  const button = document.createElement("button");
  button.classList.add(className);
  button.innerHTML = innerHTML;
  return button;
}

/**
 * Copies the given text to the clipboard and updates the button text.
 * @param {string} text - The text to copy to the clipboard.
 * @param {HTMLButtonElement} button - The button element to update.
 */
async function copyToClipboard(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    button.innerHTML = `<i class="bi bi-clipboard-check"></i> Copied!`;
  } catch (err) {
    console.error("Failed to copy text: ", err);
    button.innerHTML = `<i class="bi bi-clipboard-x-fill"></i> Failed to copy!`;
  } finally {
    setTimeout(
      () =>
        (button.innerHTML = button.innerHTML =
          `<i class="bi bi-clipboard"></i> Copy`),
      1500,
    );
  }
}

// --- Code Block Enhancement Functions ---
/**
 * Enhances code blocks with a copy button and language label.
 * @param {HTMLElement} scope - The scope to search for code blocks.
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
    if (codeBlock.className.indexOf("hljs language-") != -1)
      langName.innerText = codeBlock.className.replace("hljs language-", "");
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
 * @param {HTMLElement} scope - The scope to search for code blocks.
 */
function enhanceCodeInlines(scope) {
  scope.querySelectorAll("code").forEach((code) => {
    if (!code.classList.contains("code-block")) {
      code.classList.add("code-inline");
    }
  });
}

/**
 * Displays the attached files in the chat.
 * @param {HTMLElement} msgDiv - The message div element.
 * @param {array} attachments - An array of file objects.
 */
function displayAttachments(msgDiv, attachments) {
  if (attachments && attachments.length > 0) {
    const attachmentsDiv = document.createElement("div");
    attachmentsDiv.classList.add("attachments");
    attachmentsDiv.innerHTML = "<strong>Attachments:</strong><br>";

    attachments.forEach((file) => {
      if (file.type.startsWith("image/")) {
        // Create an image element
        const img = document.createElement("img");
        img.src = `data:${file.type};base64,${file.content}`;
        img.alt = file.filename; // Set the alt attribute for accessibility
        img.style.maxWidth = "50px"; // Limit the image width
        img.style.maxHeight = "50px"; // Limit the image height
        img.style.display = "block"; // Ensure it's displayed as a block element
        attachmentsDiv.appendChild(img);
      } else if (file.type.startsWith("video/")) {
        // Handle video files
        const video = document.createElement("video");
        video.alt = file.name;
        video.style.maxWidth = "50px"; // Adjust as needed
        video.style.maxHeight = "50px"; // Adjust as needed
        video.style.marginRight = "5px"; // Add some spacing
        video.controls = false;
        video.muted = true;

        // Create a source element for the video
        const source = document.createElement("source");
        source.src = `data:${file.type};base64,${file.content}`;
        source.type = file.type; // Set the correct MIME type

        video.appendChild(source);
        attachmentsDiv.appendChild(video);
      } else {
        // For other file types (e.g., text), create a link
        const fileLink = document.createElement("a");
        fileLink.href = `data:${file.type};base64,${file.content}`; // Create a data URL
        fileLink.download = file.filename; // Set the filename for download
        fileLink.textContent = file.filename;
        attachmentsDiv.appendChild(fileLink);
      }
      attachmentsDiv.appendChild(document.createElement("br")); // Add a line break
    });

    msgDiv.appendChild(attachmentsDiv);
  }
}

// --- Message Handling Functions ---
/**
 * Adds a message to the chat box.
 * @param {HTMLElement} chatBox - The chat box element.
 * @param {object} msg - The message object.
 */
function addMessageToChatBox(chatBox, msg) {
  const msgDiv = document.createElement("div");
  msgDiv.classList.add("message");
  msgDiv.id = msg.id;
  msgDiv.classList.add(msg.role === "user" ? "user-msg" : "ai-msg");
  if (msg.content !== "" && msg.content.startsWith("Uploading Video: ")) {
    const thinkingDiv = document.createElement("div");
    thinkingDiv.classList.add("thinking-loader");
    thinkingDiv.innerHTML = `
      Uploading Video: 
      <div class="dot"></div>
      <div class="dot"></div>
      <div class="dot"></div>
    `;
    msgDiv.appendChild(thinkingDiv);
  }
  else if(msg.content !== "")
      msgDiv.innerHTML = marked.parse(msg.content);
  else {
    const thinkingDiv = document.createElement("div");
    thinkingDiv.classList.add("thinking-loader");
    thinkingDiv.innerHTML = `
    <div class="dot"></div>
    <div class="dot"></div>
    <div class="dot"></div>
`;
    msgDiv.appendChild(thinkingDiv);
  }

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
  msgDiv.appendChild(deleteButton);

  displayAttachments(msgDiv, msg.attachments);

  chatBox.appendChild(msgDiv);
  chatBox.scrollTop = chatBox.scrollHeight;
}

/**
 * Deletes a message from the server and updates the chat.
 * @param {string} messageId - The ID of the message to delete.
 */
function deleteMessage(messageId) {
  socket.emit("delete_message", { message_id: messageId });
}

/**
 * Updates a message in the chat box.
 * @param {object} msg - The updated message object.
 */
function updateMessageInChatBox(msg) {
  const msgDiv = document.getElementById(msg.id);
  msgDiv.innerHTML = marked.parse(msg.content);

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
  msgDiv.appendChild(deleteButton);

  displayAttachments(msgDiv, msg.attachments);

  enhanceCodeBlocks(msgDiv);
  enhanceCodeInlines(msgDiv);
  const chatBox = document.getElementById("chat-box");
}

/**
 * Updates the entire chat display with the given history.
 * @param {array} history - An array of message objects.
 */
function updateChatDisplay(history) {
  const chatBox = document.getElementById("chat-box");
  chatBox.innerHTML = "";
  history.forEach((msg) => addMessageToChatBox(chatBox, msg));

  chatBox.scrollTop = chatBox.scrollHeight;
  enhanceCodeBlocks(chatBox);
  enhanceCodeInlines(chatBox);
}

// --- Initialization and Socket Event Handling ---
const socket = io();

/**
 * Initializes the chat by fetching the chat history from the server.
 */
function initializeChat() {
  socket.emit("get_chat_history");
}

socket.on("connect", () => {
  console.log("Reconnected to the server.");
  socket.emit("get_chat_history");
});

socket.on("chat_update", updateChatDisplay);
socket.on("updated_msg", updateMessageInChatBox);

// Global variable to store file information (name and content)
let fileContents = [];

// Function to display file names in boxes with delete buttons
function displayFileNames() {
  const displayArea = document.getElementById("file-display-area");
  displayArea.innerHTML = ""; // Clear previous content
  displayArea.style.display = "flex"; // Display file boxes side by side
  displayArea.style.flexWrap = "wrap"; // Allow wrapping to the next line

  fileContents.forEach((fileData, index) => {
    const fileBox = document.createElement("div");
    fileBox.classList.add("file-box"); // Add a class for styling
    console.log("fileData.type: ", fileData.type);
    if (fileData.type.startsWith("image/")) {
      // Create an image element for image files
      const img = document.createElement("img");
      img.src = `data:${fileData.type};base64,${fileData.content}`;
      img.alt = fileData.name;
      img.style.maxWidth = "50px"; // Adjust as needed
      img.style.maxHeight = "50px"; // Adjust as needed
      img.style.marginRight = "5px"; // Add some spacing
      fileBox.appendChild(img);
    } else if (fileData.type.startsWith("video/")) {
      const video = document.createElement("video");
      video.src = `data:${fileData.type};base64,${fileData.content}`;
      video.alt = fileData.name;
      video.style.maxWidth = "50px"; // Adjust as needed
      video.style.maxHeight = "50px"; // Adjust as needed
      video.style.marginRight = "5px"; // Add some spacing
      video.controls = false;
      video.muted = true;
      fileBox.appendChild(video);
    } else {
      // Create a span for the filename for other files
      const fileNameSpan = document.createElement("span");
      fileNameSpan.textContent = fileData.name;
      fileBox.appendChild(fileNameSpan);
    }

    const deleteButton = document.createElement("button");
    deleteButton.classList.add("delete-file-button");
    deleteButton.innerHTML = '<i class="bi bi-x"></i>'; // Cross icon
    deleteButton.addEventListener("click", () => {
      // Remove the file from the array
      fileContents.splice(index, 1);
      // Update the display
      displayFileNames();
    });
    fileBox.appendChild(deleteButton);

    displayArea.appendChild(fileBox);
  });
}

// --- Event Listeners ---
document.getElementById("chat-form").addEventListener("submit", function (e) {
  e.preventDefault();
  sendMessage();
});

document
  .getElementById("message-input")
  .addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.shiftKey) {
      insertNewlineAtCursor(this);
      e.preventDefault();
      updateTextareaRows();
    } else if (e.key === "Enter") {
      e.preventDefault();
      sendMessage();
    }
  });

document.getElementById("message-input").addEventListener("input", function () {
  updateTextareaRows();
});

// Update the file selected text and store the file contents
document
  .getElementById("file-input")
  .addEventListener("change", async function () {
    if (this.files && this.files.length > 0) {
      for (let i = 0; i < this.files.length; i++) {
        const file = this.files[i];
        const supportedImageTypes = [
          "image/blp",
          "image/bmp",
          "image/dds",
          "image/dib",
          "image/eps",
          "image/gif",
          "image/icns",
          "image/ico",
          "image/im",
          "image/jpeg",
          "image/jpeg2000",
          "image/mpo",
          "image/msp",
          "image/pcx",
          "image/pfm",
          "image/png",
          "image/ppm",
          "image/sgi",
          "image/spider",
          "image/tga",
          "image/tiff",
          "image/webp",
          "image/xbm",
          "image/cur",
          "image/dcx",
          "image/fits",
          "image/fli",
          "image/flic",
          "image/fpx",
          "image/ftex",
          "image/gbr",
          "image/gd",
          "image/imt",
          "image/iptc",
          "image/mcidas",
          "image/mic",
          "image/pcd",
          "image/pixar",
          "image/psd",
          "image/qoi",
          "image/sun",
          "image/wal",
          "image/wmf",
          "image/emf",
          "image/xpm",
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
          "video/3gpp"
        ]
        if (
          file.type.startsWith("text/")
          || supportedImageTypes.includes(file.type)
          || supportedVidTypes.includes(file.type)
        ) {
          try {
            let content = await readFileAsBase64(file); // Read as Base64 for images
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

    displayFileNames(); // Display the file names
  });

// Constants
const CHUNK_SIZE = 1024 * 1024; // 1MB chunks
let videoId = null; // Unique ID for the video being uploaded

// Helper function to generate a unique ID (UUID v4)
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Modified sendMessage function
async function sendMessage() {
    const input = document.getElementById("message-input");
    const message = input.value;

    const filesData = [];

    for (let i = 0; i < fileContents.length; i++) {
        const fileData = fileContents[i];
        if (fileData.type.startsWith("video/")) {
            // Upload video in chunks
            videoId = generateUUID(); // Generate a unique video ID
            await uploadVideoInChunks(fileData.content, fileData.name, videoId);
            filesData.push({
                filename: fileData.name,
                type: fileData.type,
                id: videoId // Send the videoId to the server
            });
        } else {
            // Send other file types as before
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

    // Emit the 'send_message' event to the server
    socket.emit("send_message", { message: message, files: filesData });
}

// New function to upload video in chunks
async function uploadVideoInChunks(base64Video, filename, videoId) {
    const totalChunks = Math.ceil(base64Video.length / CHUNK_SIZE);

    socket.emit("start_upload_video", videoId); // Notify server of upload start

    for (let i = 0; i < totalChunks; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, base64Video.length);
        const chunk = base64Video.substring(start, end);

        socket.emit("upload_video_chunck", {
            id: videoId,
            chunck: chunk,
            idx: i,
            filename: filename
        });
        console.log(`Sent chunk ${i + 1} of ${totalChunks}`);
        // await new Promise(resolve => setTimeout(resolve, 10)); // Optional: Add a small delay
    }

    socket.emit("end_upload_video", videoId); // Notify server of upload completion
    console.log(`Video "${filename}" uploaded successfully!`);
}

// Helper function to read a file as Base64
function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => {
      resolve(reader.result.split(",")[1]); // Extract the base64 part
    };

    reader.onerror = () => {
      reject(reader.error);
    };

    reader.readAsDataURL(file); // Read as Data URL
  });
}

// --- Textarea Helper Functions ---
/**
 * Inserts a newline character at the cursor position in the textarea.
 * @param {HTMLTextAreaElement} textarea - The textarea element.
 */
function insertNewlineAtCursor(textarea) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const value = textarea.value;
  textarea.value =
    value.substring(0, start) + "\n" + value.substring(end);
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
