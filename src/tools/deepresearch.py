# deepresearch.py
import uuid
import duckduckgo_search
import duckduckgo_search.exceptions
import concurrent.futures
import threading
import time
import requests
import traceback
from rich import print
from firecrawl import FirecrawlApp
from typing import Any, Callable, Optional, TypedDict
from google.genai import types
from global_shares import global_shares
import config
import prompt
from utils import retry

class FetchModelMD(TypedDict):
    # "og:description": str
    # "og:image:width": str
    # "og:locale": str
    # "google-signin-scope": str
    # "google-signin-client-id": str
    # "og:image": str
    # "og:title": str
    # "twitter:card": str
    # "og:image:height": str
    # "og:url": str
    title: str
    ogTitle: str
    language: str
    ogDescription: str
    viewport: str
    favicon: str
    ogUrl: str
    ogImage: str
    ogLocale: str
    description: str
    scrapeId: str
    sourceURL: str
    url: str
    statusCode: int


class FetchModel(TypedDict):
    markdown: str
    # screenshot: str  # url of the website screenshot
    links: list[str]  # links in the website
    # metadata: FetchModelMD

class FetchLimiter:
    _instance: Optional["FetchLimiter"] = None
    _lock: threading.Lock = threading.Lock()
    _semaphore: threading.Semaphore = threading.Semaphore(2)  # Limit to 2 concurrent requests
    calls: int = 0
    period: int = 60  # seconds
    max_calls: int = 10
    last_reset: float = 0.0

    def __new__(cls) -> "FetchLimiter":
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance.last_reset = time.time()
            return cls._instance

    def __call__(self, func: Callable) -> Callable:
        def limited_func(*args, **kwargs):
            with self._semaphore:  # Acquire semaphore to limit concurrent requets
                with self._lock:
                    now = time.time()
                    if now - self.last_reset > self.period:
                        self.calls = 0
                        self.last_reset = now

                    while self.calls >= self.max_calls:
                        sleep_time = self.last_reset + self.period - now
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                        now = time.time()
                        if now - self.last_reset > self.period:
                            self.calls = 0
                            self.last_reset = now

                    self.calls += 1
                try:
                    return func(*args, **kwargs)
                finally:
                    pass
        return limited_func

class Topic:
    topic: str
    id: str
    sub_topics: list["Topic"]
    queries: Optional[list[str]]
    urls: list[str] = []
    fetched_content: Optional[list[
        tuple[
            str, # url
            str, # fetched content
            list[str] # linkes on site
        ]]]
    researched: bool
    def __init__(
        self,
        topic: str,
        id: Optional[str] = None,
        sub_topics: Optional[list["Topic"]] = None,
        queries: Optional[list[str]] = None,
        sites: Optional[list[str]] = None,
        fetched_content: Optional[list[
            tuple[
                str, # url
                str, # fetched content
                list[str] # linkes on site
            ]]] = None,
        researched: Optional[bool] = None
    ):
        self.topic = topic
        self.id = id if id else str(uuid.uuid4())
        self.sub_topics = sub_topics if sub_topics else []  # Subtopics
        self.queries = queries if queries else queries  # Queries to search online for
        self.fetched_content = fetched_content if fetched_content else None
        self.researched = researched if researched else False
        self.urls = sites if sites else []

    def for_ai(self, id: Optional[str] = None, depth: int = 0) -> str:
        """Format topic details for AI processing in Markdown format."""
        header = "#" * (depth + 1)  # Determine heading level
        details = f"#{header} {self.topic}\n\n"
        details += f"{"This Topic is Newly searched online" if self.id == id else ""}\n"
        details += f"{"This is the main Topic/Question Searched by user." if not depth else ""}\n"
        details += f"**ID:** {self.id}\n"
        details += f"**Researched:** {'Yes' if self.researched else 'No'}  \n\n"

        if self.queries:
            details += f"{header} Queries Searched online: \n"
            for query in self.queries:
                details += f"- {query}\n"
            details += "\n"

        if self.fetched_content:
            details += f"{header} Fetched Content:\n"
            for url, markdown, links in self.fetched_content:
                details += f"- {url}:\n```md\n{markdown}\nExtracted Linkes in Webpage:\n{"\n".join(links)}```\n\n"

        if self.sub_topics:
            details += f"{header} Subtopics:\n"
            for sub in self.sub_topics:
                details += sub.for_ai(id, depth + 1) + "\n"

        return details

    def get_unresearched_topic(self) -> "Topic | None":
        """Recursively find the first unresearched topic."""
        for topic in self.sub_topics:
            if not topic.researched:
                return topic.get_unresearched_topic() or topic
        if not self.researched:
            return self
        return None

    def add_topic(self, parent_id: str, topic: "Topic") -> bool:
        if self.id == parent_id:
            self.sub_topics.append(topic)
            return True
        for sub_topic in self.sub_topics:
            if sub_topic.add_topic(parent_id, topic):
                return True
        return False

    def add_site(self, id: str, site: str):
        if self.id == id:
            self.urls.append(site)
            self.researched = False
        for sub_topic in self.sub_topics:
            if sub_topic.add_site(id, site):
                self.urls.append(site)
                self.researched = False

    def topic_tree(self, indent: str = "") -> str:
        """Returns a string representation of the topic tree in ANSI format."""
        tree = f"{indent}{self.topic}\n"
        for i, sub_topic in enumerate(self.sub_topics):
            if i < len(self.sub_topics) - 1:
                tree += sub_topic.topic_tree(indent + "├── ")
            else:
                tree += sub_topic.topic_tree(indent + "└── ")
        return tree

    def jsonify(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "id": self.id,
            "sub_topics": [_.jsonify() for _ in self.sub_topics],
            "queries": self.queries,
            "urls": self.urls,
            "fetched_content": self.fetched_content,
            "researched": self.researched
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "Topic":
        return Topic(
            topic=data["topic"],
            id=data.get("id"),
            sub_topics=data.get("sub_topics"),
            queries=data.get("queries"),
            sites=data.get("urls"),
            fetched_content=data.get("fetched_content"),
            researched=data.get("researched"),
        )

class DeepResearcher:
    app: FirecrawlApp
    query: str
    topic: Topic
    max_topics: int | None # None for inf
    max_search_queries: int | None  # None for inf
    max_search_results: int | None   # None for any
    call_back: Callable[[dict[str, Any] | None], None]
    ddgs: duckduckgo_search.DDGS

    def __init__(
        self, query: str, max_topics: Optional[int] = None, max_search_queries: int = 5, max_search_results: Optional[int] = None, call_back: Callable[[dict[str, Any] | None], None] = lambda x: None
    ):
        self.app = FirecrawlApp(
            api_key=config.FIRECRAWL_API, api_url=config.FIRECRAWL_ENDPOINT
        )
        self.query = query
        self.call_back = call_back
        self.max_topics = max_topics
        self.max_search_queries = max_search_queries
        self.max_search_results = max_search_results
        self.ddgs = duckduckgo_search.DDGS()
        self.topic = Topic(topic=query)

    def _is_query_question(self) -> bool:
        return (
            retry(max_retries=float("inf"))(global_shares["client"].models.generate_content)(
                model="tunedModels/question-detactor-e0adnas2gayt",
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                text=prompt.QUESTION_DETECTOR_USR_INSTR.format(query=self.query)
                            )
                        ],
                    )
                ],
                config=types.GenerateContentConfig(temperature=0),
            )
            .candidates[0]  # type: ignore
            .content.parts[0]  # type: ignore
            .text
            == "Yes"
        )  # type: ignore

    def analyse_add_topic(self, id: Optional[str] = None) -> str:
        def add_topic(parent_id: str, topic: str, sites: Optional[list[str]] = None, queries: Optional[list[str]] = None) -> str:
            """
            Adds a new subtopic under an existing topic in the research tree.

            You MUST only use this when:
            - The new topic provides **meaningful depth, clarification, or a new angle**
            - It is directly relevant to the main topic or its subtopics
            - The need for it arises from the **content of existing research**
            - You can generate **specific, well-scoped search queries** to guide research
            - It is not a duplicate or trivial variation of an existing topic

            Arguments:
            - parent_id (str, required): ID of the topic under which this subtopic logically belongs
            - topic (str, required): A concise, clear title for the new subtopic
            - sites (list[str], optional): List of high-value external URLs that should be explored under this topic (optional)
            - queries (list[str], optional): A list of diverse, targeted search queries that will drive initial research

            Returns:
            - str: The ID of the newly created subtopic

            🚫 Do NOT use if:
            - The tree is already complete or near-complete
            - The idea is vague, redundant, or unsupported by content
            - There are more than two existing unresearched subtopics *unless* this one adds essential clarity

            ✅ You MAY call this multiple times if each new subtopic meets all quality criteria
            """
            _topic = Topic(topic=topic, sites=sites, queries=queries)
            self.topic.add_topic(parent_id, _topic)
            self.call_back({"action": "topic_updated", "topic": self.topic.jsonify()})
            return _topic.id

        def add_site(id: str, site: str):
            """
                Adds a specific external link to an existing topic for deeper or manual research follow-up.

                You MUST use this when:
                - A high-value external page (e.g., documentation, research paper, niche blog) is discovered
                - The page contains **content not surfaced by existing search results** but important to the topic
                - The link is highly relevant and deepens understanding of the associated topic

                Arguments:
                - id (str, required): The ID of the topic this link belongs to
                - site (str, required): The full URL of the external resource

                🚫 Do NOT use this:
                - For generic, low-value, or loosely related links
                - When the content is already covered by search results
                - Just to add links—only use when the link clearly supports research

                ✅ You MAY use this without adding a new topic
                ✅ Especially useful when researching documentation-heavy domains
            """
            self.topic.add_site(id, site)
            self.call_back({"action": "topic_updated", "topic": self.topic.jsonify()})

        add_topic_tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration.from_callable_with_api_option(
                    callable=add_topic
                ),
                types.FunctionDeclaration.from_callable_with_api_option(
                    callable=add_site
                )
            ]
        )
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(text=f"Topic Tree:\n{self.topic.topic_tree()}\n\n{self.topic.for_ai(id)}"),
                    types.Part(text=prompt.ADD_TOPIC_USR_INSTR.format(breadth=f"less than {self.max_search_queries}" if self.max_search_queries else "2-4")),
                ],
            )
        ]
        text: str = ""
        while True:
            result = retry(max_retries=float("inf"))(global_shares["client"].models.generate_content)(
                model="gemini-2.0-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True, maximum_remote_calls=None
                    ),
                    tools=[add_topic_tool],
                    system_instruction=prompt.ADD_TOPIC_SYS_INSTR.format(breadth=f"less than {self.max_search_queries}" if self.max_search_queries else "2-4")
                ),
            )
            called: bool = False
            if (
                result.candidates
                and result.candidates[0].content
                and result.candidates[0].content.parts
            ):
                for part in result.candidates[0].content.parts:
                    if part.text:
                        if contents[-1].role == "model":
                            contents[-1].parts[-1].text += part.text # type: ignore
                        else:
                            contents.append(types.Content(role="model", parts=[types.Part(text=part.text)]))
                        text += part.text
                    elif part.function_call:
                        if (
                            part.function_call.name == "add_topic"
                            and part.function_call.args
                        ):
                            try:
                                added_topic_id = add_topic(part.function_call.args["parent_id"], part.function_call.args["topic"], part.function_call.args.get("sites"), part.function_call.args.get("queries"))
                            except Exception as e:
                                if contents[-1].role == "model":
                                    contents[-1].parts.append(part) #type: ignore
                                else:
                                    contents.append(
                                        types.Content(
                                            role="model",
                                            parts=[part]
                                        )
                                    )
                                contents.append(
                                    types.Content(
                                        role="user",
                                        parts=[types.Part(function_response=types.FunctionResponse(name="add_topic", id=part.function_call.id, response={"error": str(e)}))]
                                    )
                                )
                                called = True
                                text += f'$%fail call=`add topic` args=`parent_id="{part.function_call.args.get("parent_id")}", topic="{part.function_call.args.get("topic")}", sites={part.function_call.args.get("sites")}, queries={part.function_call.args.get("queries")}, error="{e}"`%$'
                                continue
                            if contents[-1].role == "model":
                                contents[-1].parts.append(part) #type: ignore
                            else:
                                contents.append(
                                    types.Content(
                                        role="model",
                                        parts=[part]
                                    )
                                )
                            contents.append(
                                types.Content(
                                    role="user",
                                    parts=[types.Part(function_response=types.FunctionResponse(name="add_topic", id=part.function_call.id, response={"output": f"Topic Added with ID {added_topic_id}"}))]
                                )
                            )
                            called = True
                            text += f'$%successful call=`add topic` args=`parent_id="{part.function_call.args.get("parent_id")}", topic="{part.function_call.args.get("topic")}", sites={part.function_call.args.get("sites")}, queries={part.function_call.args.get("queries")}`%$'
                        elif (
                            part.function_call.name == "add_site"
                            and part.function_call.args
                        ):
                            try:
                                add_site(part.function_call.args["id"], part.function_call.args["site"])
                            except Exception as e:
                                if contents[-1].role == "model":
                                    contents[-1].parts.append(part) #type: ignore
                                else:
                                    contents.append(
                                        types.Content(
                                            role="model",
                                            parts=[part]
                                        )
                                    )
                                contents.append(
                                    types.Content(
                                        role="user",
                                        parts=[types.Part(function_response=types.FunctionResponse(name="add_site", id=part.function_call.id, response={"error": str(e)}))]
                                    )
                                )
                                called = True
                                continue
                                text += f'$%fail call=`add site` args=`id="{part.function_call.args.get("id")}", site={part.function_call.args.get("site")}, error="{e}"`%$'
                            if contents[-1].role == "model":
                                contents[-1].parts.append(part) #type: ignore
                            else:
                                contents.append(
                                    types.Content(
                                        role="model",
                                        parts=[part]
                                    )
                                )
                            contents.append(
                                types.Content(
                                    role="user",
                                    parts=[types.Part(function_response=types.FunctionResponse(name="add_site", id=part.function_call.id, response={"output": f"Succesfully Added url to reseaearch for topic with id {part.function_call.args["id"]}"}))]
                                )
                            )
                            called = True
                            text += f'$%successful call=`add site` args=`id="{part.function_call.args.get("id")}", site={part.function_call.args.get("site")}`%$'
            if not called:
                break
            contents[0].parts[0].text = f"Topic Tree:\n{self.topic.topic_tree()}\n\n{self.topic.for_ai(id)}"  #type: ignore
            return text


    def _generate_queries(self, topic: str) -> list[str]:
        """Generates search queries for a given topic using AI."""
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=prompt.QUERY_GEN_USR_INSTR.format(breadth=f"less than {self.max_search_queries}" if self.max_search_queries else "2-4", topic=topic)
                    )
                ],
            ),
            types.Content(
                role="model",
                parts=[
                    types.Part(text='Search Queries:\n"')
                ]
            )
        ]
        result = retry(max_retries=float("inf"))(global_shares["client"].models.generate_content)(
            model="gemini-2.0-flash",
            contents=contents,
            config=types.GenerateContentConfig(temperature=0.5, system_instruction=prompt.QUERY_GEN_SYS_INSTR),
        )
        queries_str: str = result.candidates[0].content.parts[0].text  # type: ignore
        queries = queries_str.splitlines()
        return [q.strip()[:-1] if i == 0 else q.strip()[1:-1] for i, q in enumerate(queries) if q.strip()]

    @retry(max_retries=float("inf"))
    def _search_online(self, query: str) -> list[str]:
        """Searches DuckDuckGo for a query and returns a list of URLs."""
        results = self.ddgs.text(query, backend="lite", safesearch="off", max_results=self.max_search_results)
        linkes = [result["href"] for result in results]
        self.call_back({"action": "search", "query": query, "linkes": linkes})
        return linkes

    def _search_and_fetch(self, unresearched_topic: Topic, visited_urls: set[str]):

        def fetch_with_handling(url: str, executor) -> tuple[str, str, list[str]] | None:
            try:
                self.call_back({"action": "fetching_url", "url": url})
                fetch_model = self.fetch_url(url)
                return (url, fetch_model["markdown"], fetch_model["links"])
            except Exception as e:
                print(f"Error fetching URL {url}: {e}")
                traceback.print_exc()
                return None

        def search_and_fetch_query(query: str, executor: concurrent.futures.ThreadPoolExecutor):
            urls = self._search_online(query)
            results = []
            c_urls = []
            for url in urls:
                if url not in visited_urls:
                    visited_urls.add(url)
                    c_urls.append(url)
            url_futures = [executor.submit(fetch_with_handling, url, executor) for url in c_urls]
            for future in concurrent.futures.as_completed(url_futures):
                result = future.result()
                if result:
                    results.append(result)
            return results

        def fetch_urls(urls: list[str], executor: concurrent.futures.ThreadPoolExecutor):
            results = []
            c_urls = []
            for url in urls:
                if url not in visited_urls:
                    visited_urls.add(url)
                    c_urls.append(url)
            url_futures = [executor.submit(fetch_with_handling, url, executor) for url in c_urls]
            for future in concurrent.futures.as_completed(url_futures):
                result = future.result()
                if result:
                    results.append(result)
            return results

        if unresearched_topic.fetched_content is None:
            unresearched_topic.fetched_content = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=21 + len(unresearched_topic.queries or ())) as executor:
            futures = [executor.submit(search_and_fetch_query, query, executor) for query in unresearched_topic.queries or ()]
            futures.append(executor.submit(fetch_urls, unresearched_topic.urls, executor))
            for future in concurrent.futures.as_completed(futures):
                results = future.result()
                unresearched_topic.fetched_content.extend(results)

    def research(self) -> str:
        current_depth: int = 0
        visited_urls: set[str] = set()
        while True:
            unresearched_topic = self.topic.get_unresearched_topic()
            if not unresearched_topic:
                break

            if not unresearched_topic.queries:
                unresearched_topic.queries = self._generate_queries(unresearched_topic.topic)
                self.call_back({})

            self._search_and_fetch(unresearched_topic, visited_urls)

            unresearched_topic.researched = True
            if current_depth >= (self.max_topics or float("inf")):
                break
            current_depth += 1
            self.call_back({"action": "thinking", "thoughts": self.analyse_add_topic(unresearched_topic.id)})

        report = self._generate_report()
        return report

    def _generate_report(self) -> str:
        """Generates a final report summarizing the research."""
        self.call_back({"action": "generating_report"})
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(text=f"Topic Tree:\n{self.topic.topic_tree()}\n\n{self.topic.for_ai()}"),
                    types.Part(text=prompt.REPORT_GEN_USR_INSTR.format(topic=self.topic.topic))
                ],
            )
        ]
        report_str: str = ""
        while True:
            result = retry(max_retries=float("inf"))(global_shares["client"].models.generate_content)(
                model="gemini-2.0-flash-thinking-exp-01-21",
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    system_instruction=prompt.REPORT_GEN_SYS_INSTR),
            )
            if (
                result.candidates
                and result.candidates[0].content
                and result.candidates[0].content.parts
                and result.candidates[0].content.parts[0].text
            ):
                report_str += result.candidates[0].content.parts[0].text
                if len(contents) == 1:
                    contents[1].parts[0].text += result.candidates[0].content.parts[0].text # type: ignore
                else:
                    contents[1].parts[0].text += result.candidates[0].content.parts[0].text # type: ignore
                if result.candidates[0].finish_reason != types.FinishReason.MAX_TOKENS:
                    break

        return report_str

    def fetch_url(self, url: str, wait_for: int = 4000) -> FetchModel:
        while True:
            scrape_result = retry(max_retries=float("inf"))(FetchLimiter()(self.app.scrape_url))(
                url,
                params={
                    "formats": ["markdown", "links"], #, "screenshot@fullPage"],
                    "waitFor": wait_for,
                    "proxy": "stealth",
                    "timeout": 30_000,
                    "removeBase64Images": True,
                },
            )
            if scrape_result: return scrape_result
        img = retry(max_retries=float("inf"))(requests.get)(scrape_result["screenshot"]) if scrape_result.get("screenshot") else None
        contents: list[Any] = [
            types.Content(
                role="user",
                parts=[
                    *(
                        (types.Part(inline_data=types.Blob(data=img.content, mime_type=img.headers.get("Content-Type"))),)
                        if img
                        else ()
                    ),
                    types.Part(
                        text=f"**Input Markdown:**\n\n```md\n{scrape_result['markdown']}\n```"
                    ),
                    types.Part(
                        text=prompt.FETCH_CLEANER_USR_INSTR
                    ),
                ],
            ),
            types.Content(
                role="model", parts=[types.Part(text="**Output Markdown:**\n```md\n")]
            ),
        ]
        md: str = ""
        while True:
            result = retry(max_retries=float("inf"))(global_shares["client"].models.generate_content)(
                model="gemini-2.0-flash-lite-001",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=prompt.FETCH_CLEANER_SYS_INSTR,
                    temperature=0.1,
                    http_options=types.HttpOptions(timeout=60_000)
                ),
            )
            if (
                result.candidates
                and result.candidates[0].content
                and result.candidates[0].content.parts
                and result.candidates[0].content.parts[0].text
            ):
                md += result.candidates[0].content.parts[0].text
                contents[1].parts[0].text += result.candidates[0].content.parts[0].text
                if result.candidates[0].finish_reason != types.FinishReason.MAX_TOKENS:
                    break
        scrape_result["markdown"] = md[:-3]
        return scrape_result

def DeepResearch(query: str, max_topics: Optional[int] = None, max_search_queries: int = 5, max_search_results: Optional[int] = None) -> str:
    """\
    Dose the Deep Research on given query, query can be question or topic to be reseatch on.
    """
    ... # dummy function for AI refrence

# DeepResearcher(max_depth=10, query="list of presidents of india, some information about them, and their achievements").research()
# exit(0)
