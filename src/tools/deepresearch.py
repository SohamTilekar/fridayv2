# deepresearch.py
import uuid
import logging
import concurrent.futures
from threading import Lock
import requests
import traceback
from rich import print
from typing import Any, Callable, Optional, TYPE_CHECKING, cast
from google.genai import types
from global_shares import global_shares
import prompt
import threading
import time
import utils

if TYPE_CHECKING:
    from main import Content

# Configure logging
logging.basicConfig(
    filename="deep_researcher.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class Topic:
    topic: str
    id: str
    sub_topics: list["Topic"]

    queries: list[str]
    searched_queries: list[str]

    urls: list[str] = []
    fetched_urls: list[str] = []
    failed_fetched_urls: list[str] = []

    fetched_content: Optional[
        list[
            tuple[str, str, list[str], dict]
        ]  # url  # fetched content  # links on site  # metadata
    ] = None
    sumarized_fetched_content: str = ""
    researched: bool = False
    _lock: Lock

    def __init__(
        self,
        topic: str,
        id: Optional[str] = None,
        sub_topics: Optional[list["Topic"]] = None,
        queries: Optional[list[str]] = None,
        sites: Optional[list[str]] = None,
        fetched_content: Optional[
            list[
                tuple[str, str, list[str], dict]
            ]  # url  # fetched content  # links on site  # metadata
        ] = None,
        researched: Optional[bool] = None,
        searched_queries: Optional[list[str]] = None,
        fetched_urls: Optional[list[str]] = None,
        failed_fetched_urls: Optional[list[str]] = None,
    ):
        self.topic = topic
        self.id = id if id else str(uuid.uuid4())
        self.sub_topics = sub_topics if sub_topics else []  # Subtopics
        self.queries = queries if queries else []
        self.searched_queries = searched_queries if searched_queries else []
        self.fetched_content = fetched_content if fetched_content else None
        self.researched = researched if researched else False
        self.urls = sites if sites else []
        self.fetched_urls = fetched_urls if fetched_urls else []
        self.failed_fetched_urls = failed_fetched_urls if failed_fetched_urls else []
        self._lock = Lock()

    def for_ai(self, depth: int = 0, include_details: bool = True) -> str:
        """Format topic details for AI processing in Markdown format."""
        with self._lock:
            header = "#" * (depth + 1)  # Determine heading level
            details = f"{header} {self.topic}\n\n"
            if include_details:
                details += f"{"This is the main Topic/Question Searched by user." if not depth else ""}\n"
                details += f"**ID:** {self.id}\n"
                details += f"**Researched:** {'Yes' if self.researched else 'No'}  \n\n"

            if include_details and self.queries:
                details += f"#{header} Queries Searched online: \n"
                for query in self.queries:
                    details += f"- {query}\n"
                details += "\n"

            if self.sumarized_fetched_content:
                details += f"#{header} Sumarized Fetched Content:\n"

            if self.fetched_content:
                details += f"#{header} {"Additional" if self.sumarized_fetched_content else ""} Fetched Content:\n"
                for url, markdown, links, link_info in self.fetched_content:
                    details += f"- {url}:\n```md\n{markdown}\nExtracted Linkes in Webpage:\n{"\n".join(links)}```\n\n"

            if include_details and self.sub_topics:
                details += f"#{header} Subtopics:\n"
                for sub in self.sub_topics:
                    details += sub.for_ai(depth + 1) + "\n"

            return details

    def get_unresearched_topic(self) -> list["Topic"]:
        """
        Recursively find all unresearched topics in the topic tree.
        Returns list of Topic objects that have researched=False.
        """
        unresearched = []
        with self._lock:
            for topic in self.sub_topics:
                unresearched.extend(topic.get_unresearched_topic())
            if not self.researched:
                unresearched.append(self)
        return unresearched

    def add_topic(self, parent_id: str, topic: "Topic") -> bool:
        if self.id == parent_id:
            with self._lock:
                self.sub_topics.append(topic)
                return True
        for sub_topic in self.sub_topics:
            if sub_topic.add_topic(parent_id, topic):
                return True
        return False

    def add_site(self, id: str, site: str):
        if self.id == id:
            with self._lock:
                self.urls.append(site)
                self.researched = False
                return True
        for sub_topic in self.sub_topics:
            if sub_topic.add_site(id, site):
                return True
        return False

    def topic_tree(self, indent: str = "") -> str:
        """Returns a string representation of the topic tree in ANSI format."""
        with self._lock:
            tree = f"{indent}{self.topic}\n"
            for i, sub_topic in enumerate(self.sub_topics):
                if i < len(self.sub_topics) - 1:
                    tree += sub_topic.topic_tree(indent + "├── ")
                else:
                    tree += sub_topic.topic_tree(indent + "└── ")
        return tree

    def jsonify(self) -> dict[str, Any]:
        with self._lock:
            return {
                "topic": self.topic,
                "id": self.id,
                "sub_topics": [_.jsonify() for _ in self.sub_topics],
                "queries": self.queries,
                "searched_queries": self.searched_queries,
                "urls": self.urls,
                "fetched_urls": self.fetched_urls,
                "failed_fetched_urls": self.fetched_urls,
                "fetched_content": self.fetched_content,
                "researched": self.researched,
            }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "Topic":
        return Topic(
            topic=data["topic"],
            id=data.get("id"),
            sub_topics=data.get("sub_topics"),
            queries=data.get("queries"),
            searched_queries=data.get("searched_queries"),
            sites=data.get("urls"),
            fetched_urls=data.get("fetched_urls"),
            failed_fetched_urls=data.get("failed_fetched_urls"),
            fetched_content=data.get("fetched_content"),
            researched=data.get("researched"),
        )


class DeepResearcher:
    query: str
    topic: Topic
    max_topics: int | None
    max_search_queries: int | None
    max_search_results: int | None
    call_back: Callable[[dict[str, Any] | None], None]

    # New: research control knobs
    tree_depth_limit: int
    branch_width_limit: int
    semantic_drift_limit: float
    research_detail_level: float
    planer_content: list[types.Content] = []

    class StopResearch(Exception): ...

    def __init__(
        self,
        query: str,
        max_topics: Optional[int] = None,
        max_search_queries: int = 2,
        max_search_results: int = 4,
        tree_depth_limit: int = 13,
        branch_width_limit: int = 8,
        semantic_drift_limit: float = 0.4,
        research_detail_level: float = 0.85,
        call_back: Callable[[dict[str, Any] | None], None] = lambda x: None,
    ):
        self.query = query
        self.call_back = call_back
        self.max_topics = max_topics
        self.max_search_queries = max_search_queries
        self.max_search_results = max_search_results
        self.topic = Topic(topic=query)
        self._stop_event = threading.Event()

        self.tree_depth_limit = tree_depth_limit
        self.branch_width_limit = branch_width_limit
        self.semantic_drift_limit = semantic_drift_limit
        self.research_detail_level = research_detail_level

    @property
    def stop(self):
        return self._stop_event.is_set()

    @stop.setter
    def stop(self, value: bool):
        if value:
            self._stop_event.set()

    @utils.retry(
        exceptions=utils.network_errors,
        ignore_exceptions=utils.ignore_network_error,
    )
    def summarize_sites(self, topic: Topic) -> None:
        self.call_back({"action": "summarize_sites", "topic": topic.id})

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Use an iterative approach with a worklist instead of recursion
            topics_to_process = [topic]  # Start with the initial topic
            futures = {}  # Map of topic.id to its future

            # Process all topics in the worklist
            i = 0
            while i < len(topics_to_process):
                current_topic = topics_to_process[i]
                i += 1

                if self.stop:
                    break

                # Process current topic content
                self.call_back({"action": "summarize_sites", "topic": current_topic.id})
                future = executor.submit(self._summarize_topic_content, current_topic)
                futures[current_topic.id] = future

                # Add subtopics to the worklist
                topics_to_process.extend(current_topic.sub_topics)

            # Wait for all futures to complete
            for topic_id, future in futures.items():
                if self.stop:
                    break
                try:
                    future.result()  # Get the result to propagate any exceptions
                    self.call_back(
                        {"action": "summarize_sites_complete", "topic": topic_id}
                    )
                except Exception as e:
                    print(f"Error summarizing topic content: {e}")
                    traceback.print_exc()

    def _summarize_topic_content(self, topic: Topic) -> None:
        """Helper method to summarize a single topic's content using AI."""
        tc = (
            utils.retry(
                exceptions=utils.network_errors,
                ignore_exceptions=utils.ignore_network_error,
            )(global_shares["client"].models.count_tokens)(
                model="gemini-2.0-flash",
                contents=types.Part(text=topic.for_ai(0, False)),
            ).total_tokens
            or 0
        )  # type: ignore
        if tc > 6_00_000:
            with topic._lock:
                if topic.fetched_content:
                    summarized_sites = []
                    for url, content, links, metadata in topic.fetched_content:
                        # Check if individual site content is too large
                        site_content = [
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part(
                                        text=f"Content from {url}:\n```md\n{content}\n```"
                                    ),
                                    types.Part(text=prompt.SUMMARIZE_SITES_USER_INSTR),
                                ],
                            )
                        ]

                        site_tc = (
                            utils.retry(
                                exceptions=utils.network_errors,
                                ignore_exceptions=utils.ignore_network_error,
                            )(global_shares["client"].models.count_tokens)(
                                model="gemini-2.0-flash", contents=site_content  # type: ignore
                            ).total_tokens
                            or 0
                        )

                        if site_tc > 3_00_000:
                            # Skip this site as it's too large
                            continue

                        # Summarize the site content if it's a reasonable size
                        if (
                            site_tc > 15_000
                        ):  # Only summarize if the content is substantial
                            # Initialize empty summary and context for continuation
                            site_summary_contents = site_content
                            summarized_content = ""

                            # Loop until summarization is complete
                            while True:
                                if self.stop:
                                    break

                                site_summary_result = utils.retry(
                                    exceptions=utils.network_errors,
                                    ignore_exceptions=utils.ignore_network_error,
                                )(global_shares["client"].models.generate_content)(
                                    model="gemini-1.5-flash-8b",
                                    contents=cast(
                                        types.ContentListUnion, site_summary_contents
                                    ),
                                    config=types.GenerateContentConfig(
                                        system_instruction="Create a concise summary of the key information."
                                    ),
                                )

                                if (
                                    site_summary_result
                                    and site_summary_result.candidates
                                    and site_summary_result.candidates[0].content
                                    and site_summary_result.candidates[0].content.parts
                                ):

                                    # Append the new content to our summary
                                    new_content = (
                                        site_summary_result.candidates[0]
                                        .content.parts[0]
                                        .text
                                    )
                                    summarized_content += new_content or ""

                                    # If there's already a model response in our contents, add to it
                                    # Otherwise, create a new model response
                                    if (
                                        len(site_summary_contents) > 1
                                        and site_summary_contents[-1].role == "model"
                                    ):
                                        site_summary_contents[-1].parts[-1].text += new_content  # type: ignore
                                    else:
                                        site_summary_contents.append(
                                            types.Content(
                                                role="model",
                                                parts=[types.Part(text=new_content)],
                                            )
                                        )

                                    # Break the loop if we're done (not truncated by token limit)
                                    if (
                                        site_summary_result.candidates[0].finish_reason
                                        != types.FinishReason.MAX_TOKENS
                                    ):
                                        break
                                else:
                                    # No valid result, use original content
                                    summarized_content = content
                                    break

                            # Add the summarized content to our sites
                            summarized_sites.append(
                                (url, summarized_content, links, metadata)
                            )
                        else:
                            # Content is small enough, keep as is
                            summarized_sites.append((url, content, links, metadata))

                    # Replace the original fetched_content with summarized content
                    topic.fetched_content = summarized_sites
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(text=topic.for_ai(0, False)),
                    types.Part(text=prompt.SUMMARIZE_TOPIC_USER_INSTR),
                ],
            )
        ]
        while True:
            if self.stop:
                break

            result = utils.retry(
                exceptions=utils.network_errors,
                ignore_exceptions=utils.ignore_network_error,
            )(global_shares["client"].models.generate_content)(
                model="gemini-2.0-flash",
                contents=cast(types.ContentListUnion, contents),
                config=types.GenerateContentConfig(
                    system_instruction=prompt.SUMMARIZE_TOPIC_SYS_INSTR.format(
                        topic=topic.topic
                    )
                ),
            )

            if (
                result
                and result.candidates
                and result.candidates[0].content
                and result.candidates[0].content.parts
            ):
                for part in result.candidates[0].content.parts:
                    if part.text:
                        if contents[-1].role == "model":
                            contents[-1].parts[-1].text += part.text  # type: ignore
                        else:
                            contents.append(
                                types.Content(
                                    role="model", parts=[types.Part(text=part.text)]
                                )
                            )
                if result.candidates[0].finish_reason != types.FinishReason.MAX_TOKENS:
                    break

        if contents[-1].role == "model" and len(contents[-1].parts or ()) > 0:
            topic.sumarized_fetched_content = contents[-1].parts[-1].text  # type: ignore
            topic.fetched_content = None

    def analyse_add_topic(self, use_thinking: bool, thinking_id: str) -> None:
        def add_topic(
            parent_id: str,
            topic: str,
            sites: Optional[list[str]] = None,
            queries: Optional[list[str]] = None,
        ) -> str:
            """\
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
                - The idea is vague, redundant, or
                unsupported by content
                - There are more than two existing unresearched subtopics *unless* this one adds essential clarity

                ✅ You MAY call this multiple times if each new subtopic meets all quality criteria
            """
            _topic = Topic(topic=topic, sites=sites, queries=queries)
            success = self.topic.add_topic(parent_id, _topic)
            if not success:
                raise Exception(f"Parent topic with ID {parent_id} not found")
            self.call_back({"action": "topic_updated"})
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
            self.call_back({"action": "topic_updated"})

        add_topic_tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration.from_callable_with_api_option(
                    callable=add_topic
                ),
                types.FunctionDeclaration.from_callable_with_api_option(
                    callable=add_site
                ),
            ]
        )
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=f"Topic Tree:\n{self.topic.topic_tree()}\n\n{self.topic.for_ai()}"
                    ),
                    types.Part(
                        text=prompt.ADD_TOPIC_USR_INSTR.format(
                            max_search_queries=self.max_search_queries,
                            tree_depth_limit=self.tree_depth_limit,
                            branch_width_limit=self.branch_width_limit,
                            semantic_drift_limit=self.semantic_drift_limit,
                            research_detail_level=self.research_detail_level,
                        )
                    ),
                ],
            )
        ]

        uicontents: list["Content"] = []
        backoff = 1
        while True:
            try:
                stream = utils.retry(
                    exceptions=utils.network_errors,
                    ignore_exceptions=utils.ignore_network_error,
                )(global_shares["client"].models.generate_content_stream)(
                    model=(
                        "gemini-2.5-flash-preview-04-17"
                        if use_thinking
                        else "gemini-2.0-flash"
                    ),
                    contents=[*self.planer_content, *contents],
                    config=types.GenerateContentConfig(
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True, maximum_remote_calls=None
                        ),
                        tools=[add_topic_tool],
                        system_instruction=prompt.ADD_TOPIC_SYS_INSTR.format(
                            max_search_queries=self.max_search_queries,
                            tree_depth_limit=self.tree_depth_limit,
                            branch_width_limit=self.branch_width_limit,
                            semantic_drift_limit=self.semantic_drift_limit,
                            research_detail_level=self.research_detail_level,
                        ),
                    ),
                )
                called: bool = False
                for result in stream:
                    if (
                        result
                        and result.candidates
                        and result.candidates[0].content
                        and result.candidates[0].content.parts
                    ):
                        part = result.candidates[0].content.parts[0]
                        if part.text:
                            if contents[-1].role == "model":
                                if part.thought and contents[-1].parts[-1].thought:  # type: ignore
                                    contents[-1].parts[-1].text += part.text  # type: ignore
                                    uicontents[-1].text += part.text  # type: ignore
                                elif not part.thought and contents[-1].parts[-1].thought:  # type: ignore
                                    contents[-1].parts.append(types.Part(text=part.text, thought=False))  # type: ignore
                                    uicontents.append(
                                        global_shares["content"](
                                            text=part.text, thought=False
                                        )
                                    )
                                elif part.thought and not contents[-1].parts[-1].thought:  # type: ignore
                                    contents[-1].parts.append(types.Part(text=part.text, thought=True))  # type: ignore
                                    uicontents.append(
                                        global_shares["content"](
                                            text=part.text, thought=True
                                        )
                                    )
                                elif not part.thought and not contents[-1].parts[-1].thought:  # type: ignore
                                    contents[-1].parts[-1].text += part.text  # type: ignore
                                    uicontents[-1].text += part.text  # type: ignore
                            else:
                                contents.append(
                                    types.Content(role="model", parts=[part])
                                )
                                uicontents.append(
                                    global_shares["content"](
                                        text=part.text, thought=bool(part.thought)
                                    )
                                )
                        elif part.function_call:
                            uicontents.append(
                                global_shares["content"](
                                    function_call=global_shares["function_call"](
                                        name=part.function_call.name,
                                        args=part.function_call.args,
                                        id=part.function_call.id,
                                    )
                                )
                            )
                            uicontents_id = uicontents[-1].function_call.id  # type: ignore
                            if (
                                part.function_call.name == "add_topic"
                                and part.function_call.args
                            ):
                                try:
                                    added_topic_id = add_topic(
                                        part.function_call.args["parent_id"],
                                        part.function_call.args["topic"],
                                        part.function_call.args.get("sites"),
                                        part.function_call.args.get("queries"),
                                    )
                                except Exception as e:
                                    if contents[-1].role == "model":
                                        contents[-1].parts.append(part)  # type: ignore
                                    else:
                                        contents.append(
                                            types.Content(role="model", parts=[part])
                                        )
                                    contents.append(
                                        types.Content(
                                            role="user",
                                            parts=[
                                                types.Part(
                                                    function_response=types.FunctionResponse(
                                                        name="add_topic",
                                                        id=part.function_call.id,
                                                        response={"error": str(e)},
                                                    )
                                                )
                                            ],
                                        )
                                    )
                                    uicontents.append(
                                        global_shares["content"](
                                            function_response=global_shares[
                                                "function_responce"
                                            ](
                                                name=part.function_call.name,
                                                response={"error": str(e)},
                                                id=uicontents_id,
                                            )
                                        )
                                    )
                                    called = True
                                    continue
                                if contents[-1].role == "model":
                                    contents[-1].parts.append(part)  # type: ignore
                                else:
                                    contents.append(
                                        types.Content(role="model", parts=[part])
                                    )
                                contents.append(
                                    types.Content(
                                        role="user",
                                        parts=[
                                            types.Part(
                                                function_response=types.FunctionResponse(
                                                    name="add_topic",
                                                    id=part.function_call.id,
                                                    response={
                                                        "output": f"Topic Added with ID {added_topic_id}"
                                                    },
                                                )
                                            )
                                        ],
                                    )
                                )
                                uicontents.append(
                                    global_shares["content"](
                                        function_response=global_shares[
                                            "function_responce"
                                        ](
                                            name=part.function_call.name,
                                            response={"output": None},
                                            id=uicontents_id,
                                        )
                                    )
                                )
                                called = True
                            elif (
                                part.function_call.name == "add_site"
                                and part.function_call.args
                            ):
                                try:
                                    add_site(
                                        part.function_call.args["id"],
                                        part.function_call.args["site"],
                                    )
                                except Exception as e:
                                    if contents[-1].role == "model":
                                        contents[-1].parts.append(part)  # type: ignore
                                    else:
                                        contents.append(
                                            types.Content(role="model", parts=[part])
                                        )
                                    contents.append(
                                        types.Content(
                                            role="user",
                                            parts=[
                                                types.Part(
                                                    function_response=types.FunctionResponse(
                                                        name="add_site",
                                                        id=part.function_call.id,
                                                        response={"error": str(e)},
                                                    )
                                                )
                                            ],
                                        )
                                    )
                                    uicontents.append(
                                        global_shares["content"](
                                            function_response=global_shares[
                                                "function_responce"
                                            ](
                                                name=part.function_call.name,
                                                response={"error": str(e)},
                                                id=uicontents_id,
                                            )
                                        )
                                    )
                                    called = True
                                    continue
                                if contents[-1].role == "model":
                                    contents[-1].parts.append(part)  # type: ignore
                                else:
                                    contents.append(
                                        types.Content(role="model", parts=[part])
                                    )
                                contents.append(
                                    types.Content(
                                        role="user",
                                        parts=[
                                            types.Part(
                                                function_response=types.FunctionResponse(
                                                    name="add_site",
                                                    id=part.function_call.id,
                                                    response={
                                                        "output": f"Succesfully Added url to reseaearch for topic with id {part.function_call.args['id']}"
                                                    },
                                                )
                                            )
                                        ],
                                    )
                                )
                                uicontents.append(
                                    global_shares["content"](
                                        function_response=global_shares[
                                            "function_responce"
                                        ](
                                            name=part.function_call.name,
                                            response={"output": None},
                                            id=uicontents_id,
                                        )
                                    )
                                )
                                called = True
                        self.call_back(
                            {
                                "action": "update_thinking",
                                "id": thinking_id,
                                "content": [_.jsonify() for _ in uicontents],
                            }
                        )
                if not called:
                    break
                if self.stop:
                    raise DeepResearcher.StopResearch()
            except Exception as e:
                if isinstance(e, utils.network_errors) and not isinstance(
                    e, utils.ignore_network_error
                ):
                    print("Error occured: ", str(e), "Sleeping :", backoff, "s")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise
            contents[0].parts[0].text = f"Topic Tree:\n{self.topic.topic_tree()}\n\n{self.topic.for_ai()}"  # type: ignore
        self.planer_content.extend(contents[1:])
        self.planer_content.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text="old topic content has been truncated due to system context window limits. The full conversation history may contain additional context not shown here."
                    )
                ],
            )
        )
        self.call_back(
            {
                "action": "done_thinking",
                "id": thinking_id,
                "content": [_.jsonify() for _ in uicontents],
            }
        )

    def _generate_queries(self, topic: str) -> list[str]:
        """Generates search queries for a given topic using AI."""
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=prompt.QUERY_GEN_USR_INSTR.format(
                            breadth=(
                                f"less than {self.max_search_queries}"
                                if self.max_search_queries
                                else "2-4"
                            ),
                            topic=topic,
                        )
                    )
                ],
            ),
            types.Content(role="model", parts=[types.Part(text='Search Queries:\n"')]),
        ]
        result = utils.retry(
            exceptions=utils.network_errors,
            ignore_exceptions=utils.ignore_network_error,
        )(global_shares["client"].models.generate_content)(
            model="gemini-2.0-flash",
            contents=cast(types.ContentListUnion, contents),
            config=types.GenerateContentConfig(
                temperature=0.5,
                system_instruction=prompt.QUERY_GEN_SYS_INSTR.format(
                    breadth=(
                        f"less than {self.max_search_queries}"
                        if self.max_search_queries
                        else "2-4"
                    )
                ),
            ),
        )
        queries_str: str = (
            result.candidates[0].content.parts[0].text
            if result
            and result.candidates
            and result.candidates[0].content
            and result.candidates[0].content.parts
            and result.candidates[0].content.parts[0].text
            else ""
        )
        if not (
            result
            and result.candidates
            and result.candidates[0].content
            and result.candidates[0].content.parts
            and result.candidates[0].content.parts[0].text
        ):
            raise ValueError("Failed to generate queries.")
        return [
            q.strip()[:-1] if i == 0 else q.strip()[1:-1]
            for i, q in enumerate(queries_str.splitlines())
            if q.strip()
        ]

    @utils.retry(
        exceptions=utils.network_errors,
        ignore_exceptions=utils.ignore_network_error,
    )
    def _search_online(self, query: str) -> list[str]:
        """Searches DuckDuckGo for a query and returns a list of URLs."""
        results = utils.searcher(
            query, safesearch="off", max_results=self.max_search_results
        )
        links = [result["href"] for result in results]
        return links

    def _search_and_fetch(
        self, unresearched_topic: Topic, visited_urls: set[str], failed_urls: set[str]
    ):
        if not unresearched_topic.queries:
            with unresearched_topic._lock:
                unresearched_topic.queries = self._generate_queries(
                    unresearched_topic.topic
                )
            self.call_back({"action": "topic_updated"})

        search_state = {
            "action": "search",
            "type": "search",
            "id": str(uuid.uuid4()),
            "topic_name": unresearched_topic.topic,
            "planed_queries": unresearched_topic.queries or [],
            "researched_queries": unresearched_topic.searched_queries or [],
            "planed_fetchurl": unresearched_topic.urls or [],
            "failed_fetchurl": unresearched_topic.failed_fetched_urls or [],
            "researched_fetchurl": unresearched_topic.fetched_urls or [],
            "urls": [],
            "fetched_urls": [],
            "fetched_failed_urls": [],
            "url_metadata": {},
        }
        self.call_back(search_state)
        search_state["action"] = "update_search"

        def fetch_with_handling(
            url: str, is_not_searched: bool
        ) -> tuple[str, str, list[str], dict] | None:
            fetch_model = self.fetch_url(url)
            if is_not_searched:  # whether it is in extra sites of topic
                search_state["planed_fetchurl"].remove(url)
            search_state["urls"].remove(url)
            if fetch_model:
                if is_not_searched:
                    search_state["researched_fetchurl"].append(url)
                search_state["fetched_urls"].append(url)
                url_info = fetch_model.get(
                    "url_display_info", {"url": url, "title": "", "favicon": ""}
                )
                search_state["url_metadata"][url] = url_info
                self.call_back(search_state)
                return (url, fetch_model["markdown"], fetch_model["links"], url_info)
            failed_urls.add(url)
            if is_not_searched:
                search_state["failed_fetchurl"].append(url)
            search_state["fetched_failed_urls"].append(url)
            self.call_back(search_state)
            return None

        def process_urls(
            urls: list[str],
            is_not_searched: bool,
            executor: concurrent.futures.ThreadPoolExecutor,
            executor_lock: Lock,
        ) -> list[tuple[str, str, list[str], dict]]:
            results = []
            search_state["urls"].extend(urls)
            self.call_back(search_state)
            futures = []

            for url in urls:
                if url not in visited_urls:
                    visited_urls.add(url)
                    # Submit the fetch task to the thread pool
                    with executor_lock:
                        future = executor.submit(
                            fetch_with_handling, url, is_not_searched
                        )
                    futures.append(future)
                else:
                    # to not append alrady visited but failed url in fetched urls
                    if url in failed_urls:
                        search_state["fetched_failed_urls"].append(url)
                    else:
                        search_state["fetched_urls"].append(url)

            # Collect results from all futures
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    print(f"Error in future execution: {e}")
                    traceback.print_exc()

            return results

        def search_and_fetch_query(
            query: str,
            executor: concurrent.futures.ThreadPoolExecutor,
            executor_lock: Lock,
        ):
            urls = self._search_online(query)
            result = process_urls(urls, False, executor, executor_lock)
            search_state["planed_queries"].remove(query)
            search_state["researched_queries"].append(query)
            with unresearched_topic._lock:
                unresearched_topic.searched_queries.append(query)
                unresearched_topic.queries = search_state["planed_queries"]
            self.call_back(search_state)
            self.call_back({"action": "topic_updated"})
            return result

        # Somewhere in your method:
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
            executor_lock = Lock()
            with unresearched_topic._lock:
                if unresearched_topic.fetched_content is None:
                    unresearched_topic.fetched_content = []
                with executor_lock:
                    futures = [
                        executor.submit(
                            search_and_fetch_query, query, executor, executor_lock
                        )
                        for query in unresearched_topic.queries
                    ]
                    futures.append(
                        executor.submit(
                            process_urls,
                            unresearched_topic.urls,
                            True,
                            executor,
                            executor_lock,
                        )
                    )

            completed = set()

            while len(completed) < len(futures):
                if self.stop:
                    raise DeepResearcher.StopResearch("Research was manually stopped.")

                try:
                    for future in concurrent.futures.as_completed(futures, timeout=0.1):
                        if future in completed:
                            continue

                        if self.stop:
                            raise DeepResearcher.StopResearch(
                                "Research was manually stopped."
                            )

                        completed.add(future)

                        try:
                            results = future.result()
                            with unresearched_topic._lock:
                                unresearched_topic.fetched_content.extend(results)
                        except Exception as e:
                            print(f"Error during concurrent execution: {e}")
                            traceback.print_exc()
                except concurrent.futures.TimeoutError:
                    # No futures completed during this 0.1s window; check self.stop again
                    continue
        with unresearched_topic._lock:
            unresearched_topic.queries = search_state["planed_queries"]
            unresearched_topic.searched_queries = search_state["researched_queries"]
            unresearched_topic.urls = search_state["planed_fetchurl"]
            unresearched_topic.failed_fetched_urls = search_state["failed_fetchurl"]
            unresearched_topic.fetched_urls = search_state["researched_fetchurl"]
            unresearched_topic.researched = True
        self.call_back({"action": "topic_updated"})

    def research(self) -> list["Content"]:
        current_depth: int = 0
        visited_urls: set[str] = set()
        failed_urls: set[str] = set()
        try:
            while not self.stop:
                unresearched_topics = self.topic.get_unresearched_topic()
                if not unresearched_topics:
                    break

                # Use ThreadPoolExecutor to process multiple unresearched topics in parallel
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(6, len(unresearched_topics))
                ) as executor:
                    futures = []

                    # Submit tasks for each unresearched topic
                    for topic in unresearched_topics:
                        if self.stop:
                            raise DeepResearcher.StopResearch()

                        # Submit the search and fetch task to the thread pool
                        future = executor.submit(
                            self._search_and_fetch, topic, visited_urls, failed_urls
                        )
                        futures.append(future)

                    completed = set()

                    while len(completed) < len(futures):
                        try:
                            # Process results as they complete
                            for future in concurrent.futures.as_completed(
                                futures, timeout=0.1
                            ):
                                if future in completed:
                                    continue

                                if self.stop:
                                    raise DeepResearcher.StopResearch(
                                        "Research was manually stopped."
                                    )

                                completed.add(future)
                                try:
                                    future.result()  # Wait for any exceptions
                                except Exception:
                                    traceback.print_exc()
                        except concurrent.futures.TimeoutError:
                            # No futures completed during this 0.1s window; check self.stop again
                            continue

                # Check if we've reached the maximum topic depth
                current_depth += 1
                if current_depth >= (self.max_topics or float("inf")):
                    break

                if self.stop:
                    raise DeepResearcher.StopResearch()

                # Analyze and add new topics after completing current batch
                tc = (
                    utils.retry(
                        exceptions=utils.network_errors,
                        ignore_exceptions=utils.ignore_network_error,
                    )(global_shares["client"].models.count_tokens)(
                        model="gemini-2.0-flash",
                        contents=[
                            types.Content(
                                role="user",
                                parts=[types.Part(text=self.topic.for_ai())],
                            )
                        ],
                    ).total_tokens
                    or 0
                )
                if tc > 9_00_000:  # 0.9 million
                    self.summarize_sites(self.topic)
                    tc = (
                        utils.retry(
                            exceptions=utils.network_errors,
                            ignore_exceptions=utils.ignore_network_error,
                        )(global_shares["client"].models.count_tokens)(
                            model="gemini-2.0-flash",
                            contents=[
                                types.Content(
                                    role="user",
                                    parts=[types.Part(text=self.topic.for_ai())],
                                )
                            ],
                        ).total_tokens
                        or 0
                    )
                if tc > 9_00_000:
                    break
                thinking_id = str(uuid.uuid4())
                self.call_back({"action": "start_thinking", "id": thinking_id})
                self.analyse_add_topic(tc < 1_86_000, thinking_id)
        except DeepResearcher.StopResearch:
            pass  # Dont care abot how much reacsher has complited

        report = self._generate_report()
        self.call_back(
            {"action": "done_generating_report", "data": [_.jsonify() for _ in report]}
        )
        return report

    def _generate_report(self) -> list["Content"]:
        """Generates a final report summarizing the research."""
        self.call_back({"action": "generating_report"})
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=f"Topic Tree:\n{self.topic.topic_tree()}\n\n{self.topic.for_ai()}"
                    ),
                    types.Part(
                        text=prompt.REPORT_GEN_USR_INSTR.format(
                            topic=self.topic.topic,
                            semantic_drift_limit=self.semantic_drift_limit,
                            research_detail_level=self.research_detail_level,
                        )
                    ),
                ],
            )
        ]
        for content in contents:
            print(content)
        report: list[Content] = []
        while True:
            model = "gemini-2.0-flash-thinking-exp-01-21"
            result = utils.retry(
                exceptions=utils.network_errors,
                ignore_exceptions=utils.ignore_network_error,
            )(global_shares["client"].models.generate_content)(
                model=model,
                contents=cast(types.ContentListUnion, contents),
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    system_instruction=prompt.REPORT_GEN_SYS_INSTR.format(
                        semantic_drift_limit=self.semantic_drift_limit,
                        research_detail_level=self.research_detail_level,
                    ),
                ),
            )
            if (
                result
                and result.candidates
                and result.candidates[0].content
                and result.candidates[0].content.parts
            ):
                for part in result.candidates[0].content.parts:
                    if part.text:
                        report.append(
                            global_shares["content"](
                                text=part.text, thought=bool(part.thought)
                            )
                        )
                        if contents[-1].role != "model":
                            contents.append(types.Content(role="model", parts=[part]))
                        else:
                            contents[-1].parts.append(part)  # type: ignore
                if result.candidates[0].finish_reason != types.FinishReason.MAX_TOKENS:
                    break

        return report

    def fetch_url(self, url: str, wait_for: int = 4000) -> Optional[utils.ScrapedData]:
        scrape_result = utils.scrape_url(
            url,
            params={
                "formats": ["markdown", "links"],
                "waitFor": wait_for,
                "proxy": "stealth",
                "timeout": 30_000,
                "removeBase64Images": True,
            },
        )
        if not scrape_result:
            return
        if "metadata" in scrape_result and scrape_result["metadata"]:
            scrape_result["url_display_info"] = {
                "url": url,
                "title": scrape_result["metadata"].get("title", "")
                or scrape_result["metadata"].get("ogTitle", ""),
                "favicon": scrape_result["metadata"].get("favicon", ""),
            }
        return scrape_result
        img = (
            utils.retry(
                exceptions=utils.network_errors,
                ignore_exceptions=utils.ignore_network_error,
            )(requests.get)(scrape_result["screenshot"])
            if scrape_result.get("screenshot")
            else None
        )
        contents: list[Any] = [
            types.Content(
                role="user",
                parts=[
                    *(
                        (
                            types.Part(
                                inline_data=types.Blob(
                                    data=img.content,
                                    mime_type=img.headers.get("Content-Type"),
                                )
                            ),
                        )
                        if img
                        else ()
                    ),
                    types.Part(
                        text=f"**Input Markdown:**\n\n```md\n{scrape_result['markdown']}\n```"
                    ),
                    types.Part(text=prompt.FETCH_CLEANER_USR_INSTR),
                ],
            ),
            types.Content(
                role="model", parts=[types.Part(text="**Output Markdown:**\n```md\n")]
            ),
        ]
        md: str = ""
        while True:
            result = utils.retry(
                exceptions=utils.network_errors,
                ignore_exceptions=utils.ignore_network_error,
            )(global_shares["client"].models.generate_content)(
                model="gemini-2.0-flash-lite-001",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=prompt.FETCH_CLEANER_SYS_INSTR,
                    temperature=0.1,
                    http_options=types.HttpOptions(timeout=60_000),
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


def DeepResearch(
    query: str,
    max_topics: int | None,
    max_search_queries: int,
    max_search_results: int,
    tree_depth_limit: int,
    branch_width_limit: int,
    semantic_drift_limit: float,
    research_detail_level: float,
) -> str:
    """\
    Performs comprehensive research on a given topic or question by automatically:
    1. Searching for relevant information online
    2. Analyzing and categorizing the search results
    3. Generating focused subtopics
    4. Gathering detailed information for each subtopic
    5. Creating a well-structured, in-depth final report/answer

    Args:
        query (str, Required): The central question or topic to research.
        max_topics (int, Optional[infinite]): Maximum number of topics in research.
        max_search_queries (int, Optional[2]): Maximum search queries to generate per topic.
        max_search_results (int, Optional[4]): Maximum search result URLs per query.
        tree_depth_limit (int, Optional[13]): Max depth allowed for topic tree expansion.
        branch_width_limit (int, Optional[8]): Max subtopics allowed per node.
        semantic_drift_limit (float, Optional[0.2]): How far subtopics may deviate from the main theme (0-1) (0: less deviation, 1: wery highly deviated).
        research_detail_level (float, Optional[0.85]): How in-depth the research should be (0-1) (0: less detail, 1: super detaild).

    Returns:
        str: A comprehensive research report containing all findings organized by topic,
             with citations, relevant links, and structured analysis.
    """
    ...  # dummy function for AI reference
