# imagen.py
import base64
import utils
from typing import TYPE_CHECKING, Optional
from google.genai import types
from global_shares import global_shares

if TYPE_CHECKING:
    from main import Content


def Imagen(prompt: str, references: Optional[list[str]] = None) -> list["Content"]:
    """\
Generates or edits an image (or multiple images) based on a text prompt, optionally using reference images for guidance.
Can also be used to generate multiple frames using a single image (video generation).

Args:
    prompt (str): A text prompt describing the desired image.  This prompt can include instructions
                    regarding the number of images to generate (e.g., "Generate 3 variations of...").
                    When generating a video, specify the number of frames and the frames per second (FPS),
                    e.g., "Generate a video with 10 frames at 24 FPS".
    references (list[str]): A list of image IDs. These IDs correspond to images previously stored
                                in the `chat_history`. The referenced images will be used as input to
                                guide the image generation process.  They can be used for tasks such as
                                style transfer, content merging, general inspiration, etc.
"""
    images: list[types.Part] = []
    for ref in references or ():
        img = global_shares["chat_history"].getImage(ref)
        if isinstance(img, tuple):
            images.extend(img)
        else:
            images.append(img)
    contents = utils.retry(
        exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error
    )(global_shares["client"].models.generate_content)(
        model="gemini-2.0-flash-exp-image-generation",
        contents=[
            types.Content(
                role="user",
                parts=[
                    *images,
                    types.Part.from_text(
                        text="Generate 1 or multiple images, directly start generating images, dont write any text just generate Images, Dont ask any follow up question."
                    ),
                    types.Part.from_text(text=prompt),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            response_modalities=[
                "image",
                "text",
            ],
            response_mime_type="text/plain",
        ),
    )
    if not contents:
        return []
    if not contents.candidates:
        return []
    parts: list[Content] = []
    for candidate in contents.candidates:
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if (
                    part.inline_data
                    and part.inline_data.data
                    and part.inline_data.mime_type
                ):
                    parts.append(
                        global_shares["content"](
                            attachment=global_shares["file"](
                                base64.b64decode(part.inline_data.data),
                                part.inline_data.mime_type,
                                filename="image",
                            )
                        )
                    )
                elif part.text:
                    parts.append(global_shares["content"](text=part.text))
    return parts
