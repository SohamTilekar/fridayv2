# imagen.py
import base64
import time
from google.genai import types
from global_shares import global_shares

def Imagen(prompt: str): # type: ignore
    """\
    Generate a image based on above prompt, You can include num of image in prompt
    """
    while not global_shares['client']:
        time.sleep(0.1)
    contents = global_shares['client'].models.generate_content(
        model="gemini-2.0-flash-exp-image-generation",
        contents= [
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
    from main import Content, File
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
