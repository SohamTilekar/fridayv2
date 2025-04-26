# Friday

Friday is a personalized AI assistant designed to help you manage tasks, access information, generate content, and interact with your computer environment through a conversational interface. Built with Python and Flask, it leverages powerful AI models and integrates various tools to provide a comprehensive support system tailored to your needs.

## ✨ Features

*   **Conversational AI:** Interact with Friday through a responsive, web-based chat interface.
*   **Dynamic UI:** A dark-themed, resizable interface with dedicated panels for chat, content, history, notifications, and scheduling.
*   **AI Model & Tool Selection:**
    *   Choose from various available AI models with different capabilities and rate limits.
    *   Select specific tools for the AI to use or let it auto-select based on the task.
    *   Control the AI's "thinking budget" for models that support dynamic thinking.
*   **Tool Integration:** Access various capabilities via AI-driven tool calls:
    *   **Web Fetching:** Get content from given website URLs, rendered as clean Markdown.
    *   **Deep Research:** Conduct in-depth, structured research on topics, visualizing the process (topic tree, search steps, fetched URLs) and generating a comprehensive report.
    *   **Reminders & Scheduling:** Set recurring or one-time reminders and manage your daily/weekly schedule using a calendar and drag-and-drop TODO lists.
    *   **Computer Access:** Execute commands, manage files (create, delete, read, write), run background processes, and link local files from a sandboxed environment.
    *   **Imagen:** Generate or edit images based on text prompts, optionally using reference images.
*   **File Handling:** Upload files (images, videos, text, PDF) via drag-and-drop or file input, display previews, and link/view them in the content panel.
*   **Code Interaction:** Display code blocks with syntax highlighting and copy-to-clipboard functionality.
*   **Grounding & Sources:** View sources and relevant information linked directly within AI responses when using supported models and tools.
*   **Notifications:** Receive important notifications in a dedicated panel, including new emails (requires Gmail setup).
*   **Persistent Chat History:** Your conversations are saved, organized into a hierarchical tree structure with branching capabilities.
*   **Keyboard Shortcuts:** Quickly navigate the UI, toggle tools, resize panels, and manage thinking budget using customizable keyboard shortcuts.

## 🚀 Setup

Follow these steps to get Friday up and running on your local machine.

### Prerequisites

*   Python 3.12+
*   Git

### 1. Clone the Repository

First, clone the project repository to your local machine:

```bash
git clone https://github.com/SohamTilekar/fridayv2 # Replace with your repository URL
cd fridayv2
```

### 2. Set up a Virtual Environment

It's highly recommended to use a virtual environment to manage dependencies:

```bash
python -m venv venv
# On Windows
.\venv\Scripts\activate
# On macOS/Linux
source ./venv/bin/activate
```

### 3. Install Dependencies

Install the required Python packages using the generated `requirements.txt` file:

```bash
pip install -r requirements.txt
```

### 4. Configuration

Copy the example configuration file and fill in your API keys and preferences.

```bash
cp src/config-example.py src/config.py
```

Now, edit `src/config.py` and update the following:

*   `GOOGLE_API`: Get your API key from the Google AI Studio or Google Cloud. **This is required.**
*   `FIRECRAWL_APIS`: Configure your Firecrawl API keys. If you're using the hosted service, you might only need one key. If self-hosting or using multiple keys, list them here as `[(RPM_LIMIT, "YOUR_API_KEY"), ...]`. `RPM_LIMIT` can be `None` if you don't know or want to enforce a limit per key. If you don't have any Firecrawl keys, you can leave it as `[(None, None)]`, but web fetching and deep research will not work.
*   `FIRECRAWL_ENDPOINT`: Set this to the URL of your self-hosted Firecrawl instance (e.g., `"http://localhost:3000"`). Use `None` for the default hosted service (`firecrawl.dev`).
*   `AI_DIR`: Specify a directory where Friday will store data (like chat history, notifications, reminders, and the computer sandbox). This should be an **absolute path** or a path relative to where you run `main.py`. Make sure this directory exists or Friday has permissions to create it.
*   `USR_NAME`: Your name, for personalization (e.g., `"LastName FirstName"`).
*   `ABOUT_YOU`: A multi-line string describing yourself for the AI to use for personalization. You can include your profession, age, country, interests, etc.
*   Review other settings like `MAX_RETRIES`, `RETRY_DELAY`, and model configurations (`Models`, `model_RPM_map`, etc.) and adjust if needed.

**Important:** After setting your `GOOGLE_API`, remove the line `raise AssertionError("Set Your Google API first")` at the end of `config.py`.

### 5. Google OAuth Credentials (Optional - for Gmail)

If you want to enable Gmail notification checking, you need to set up Google OAuth credentials.

1.  Go to the Google Cloud Console: [https://console.cloud.google.com/](https://console.cloud.google.com/)
2.  Create a new project or select an existing one.
3.  Enable the **Gmail API** for your project.
4.  Go to "APIs & Services" > "Credentials".
5.  Configure the OAuth Consent Screen (set it to "External" if you're not part of a Google Workspace organization, you'll likely need to add yourself as a test user).
6.  Create **OAuth client ID** credentials. Choose "Desktop app" as the application type.
7.  Download the `credentials.json` file.
8.  Place the downloaded `credentials.json` file in the `fridayv2/src/` directory.

The first time you run Friday with Gmail checking enabled, it will open a browser window asking you to authorize the application. After authorization, a `token.json` file will be automatically created in the `AI_DIR` you specified, storing your credentials for future use.

## ▶️ Running the Application

Once configured, ensure your virtual environment is active and run the Flask application:

```bash
python src/main.py
```

The application should start and be accessible in your web browser at `http://127.0.0.1:5000`.

The terminal where you ran the command will show logs from the server and AI interactions.

## 📂 Project Structure

*   `src/`: Contains the main Python source files.
    *   `main.py`: The main Flask application and SocketIO server. Handles chat logic, AI interaction, and tool calling.
    *   `config.py`: Your project configuration (API keys, paths, settings).
    *   `config-example.py`: Example configuration file.
    *   `global_shares.py`: Provides a way to share objects like `socketio` and the `genai.Client` instance across modules without circular imports.
    *   `lschedule.py`: Handles the local task/schedule management logic.
    *   `mail.py`: Integrates with the Gmail API for checking emails and generating notifications.
    *   `notification.py`: Defines the notification classes and manages the notification list.
    *   `prompt.py`: Contains the system instructions and prompts used by the AI models.
    *   `utils.py`: Utility functions, including retry decorators and API wrappers (Firecrawl, DuckDuckGo Search).
    *   `tools/`: Contains modules for specific AI tools.
        *   `__init__.py`: Defines the available tools and selector functions.
        *   `deepresearch.py`: Implements the deep research tool.
        *   `imagen.py`: Implements the image generation tool.
        *   `reminder.py`: Implements the reminder tool.
        *   `space.py`: Implements the computer sandbox tools.
        *   `webfetch.py`: Implements the web fetching tool.
*   `static/`: Static files for the web interface (CSS, JS, images).
    *   `style.css`: Main CSS for the chat interface and panels.
    *   `schedule.css`: CSS specifically for the schedule/calendar view.
    *   `main.js`: Main JavaScript for chat interaction, file handling, panel management, tool/model selection, and keyboard shortcuts.
    *   `schedule.js`: JavaScript for the schedule/calendar and TODO list functionality.
*   `templates/`: HTML templates for the web interface.
    *   `index.html`: The main HTML file for the chat interface.

## 🤝 Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests.

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
