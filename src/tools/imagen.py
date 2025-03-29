# imagen.py
import base64
import time
from typing import Optional
from google.genai import types
from global_shares import global_shares

def Imagen(prompt: str, references: Optional[list[str]] = None):
    """
    Generates an image (or multiple images) based on a text prompt, optionally using reference images for guidance.

    Args:
        prompt (str): A text prompt describing the desired image.  This prompt can include instructions
                      regarding the number of images to generate (e.g., "Generate 3 variations of...").
        references (list[str]): A list of image IDs. These IDs correspond to images previously stored
                                 in the `chat_history`. The referenced images will be used as input to
                                 guide the image generation process.  They can be used for tasks such as
                                 style transfer, content merging, general inspiration, etc.s
    """
    from main import chat_history, Content, File
    images: list[types.File] = []
    for ref in references or ():
        images.append(chat_history.getImage(ref))
    while not global_shares['client']:
        time.sleep(0.1)
    contents = global_shares['client'].models.generate_content(
        model="gemini-2.0-flash-exp-image-generation",
        contents=[
            *images,
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text="Generate 1 or multiple images, directly start generating images, dont write any text just generate Images, Dont ask any follow up question."),
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
        )
    )
    if not contents:
        return []
    if not contents.candidates:
        return []
    parts: list[Content] = []
    for candidate in contents.candidates:
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    parts.append(Content(text=part.text))
                elif part.inline_data and part.inline_data.data and part.inline_data.mime_type:
                    parts.append(
                        Content(attachment=File(
                                base64.b64decode(part.inline_data.data),
                                part.inline_data.mime_type,
                                filename="image"
                            )
                        )
                    )
    return parts
