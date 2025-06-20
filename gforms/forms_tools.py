import logging
import asyncio
from typing import List, Optional, Dict, Any

from mcp import types
from googleapiclient.errors import HttpError

from auth.service_decorator import require_google_service
from core.server import server
from core.utils import handle_http_errors

logger = logging.getLogger(__name__)


@server.tool()
@require_google_service("forms", "forms")
@handle_http_errors("create_form")
async def create_form(
    service,
    user_google_email: str,
    title: str,
    description: Optional[str] = None,
    document_title: Optional[str] = None,
    questions: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Create a new Google Form with optional initial questions.

    This function allows for the creation of a new Google Form, optionally populating it
    with a predefined set of questions during the initial creation call. This streamlines
    the form setup process by eliminating the need for subsequent batch update calls
    to add questions.

    Args:
        user_google_email (str): The user's Google email address. Required.
        title (str): The title of the form.
        description (Optional[str]): The description of the form.
        document_title (Optional[str]): The document title (shown in browser tab).
        questions (Optional[List[Dict[str, Any]]]): A list of dictionaries, where each
            dictionary defines a question to be added to the form. Each question
            dictionary must include a 'type' and 'title' field, and may include
            additional fields based on the question type.

            Supported 'type' values and their schemas:

            - "TEXT_QUESTION":
                {
                  "title": "string",
                  "type": "TEXT_QUESTION",
                  "description": "string (optional)",
                  "required": "boolean (optional, default: false)"
                }

            - "MULTIPLE_CHOICE_QUESTION":
                {
                  "title": "string",
                  "type": "MULTIPLE_CHOICE_QUESTION",
                  "description": "string (optional)",
                  "required": "boolean (optional, default: false)",
                  "options": ["string", ...] (required)
                }

            - "SCALE_QUESTION":
                {
                  "title": "string",
                  "type": "SCALE_QUESTION",
                  "description": "string (optional)",
                  "required": "boolean (optional, default: false)",
                  "scale_min": "integer (required, typically 0 or 1)",
                  "scale_max": "integer (required, typically 2-10)",
                  "scale_labels": {"min_value": "string", "max_value": "string"} (optional)
                }

            - "CHECKBOX_QUESTION":
                {
                  "title": "string",
                  "type": "CHECKBOX_QUESTION",
                  "description": "string (optional)",
                  "required": "boolean (optional, default: false)",
                  "options": ["string", ...] (required)
                }

            - "DATE_QUESTION":
                {
                  "title": "string",
                  "type": "DATE_QUESTION",
                  "description": "string (optional)",
                  "required": "boolean (optional, default: false)",
                  "include_time": "boolean (optional, default: false)",
                  "include_year": "boolean (optional, default: true)"
                }

            - "TIME_QUESTION":
                {
                  "title": "string",
                  "type": "TIME_QUESTION",
                  "description": "string (optional)",
                  "required": "boolean (optional, default: false)"
                }

    Returns:
        str: Confirmation message with form ID, edit URL, and responder URL.
    """
    logger.info(f"[create_form] Invoked. Email: '{user_google_email}', Title: {title}")

    form_body: Dict[str, Any] = {
        "info": {
            "title": title
        }
    }
    
    if description:
        form_body["info"]["description"] = description
        
    if document_title:
        form_body["info"]["documentTitle"] = document_title # Corrected from document_title to documentTitle

    created_form = await asyncio.to_thread(
        service.forms().create(body=form_body).execute
    )

    form_id = created_form.get("formId")
    edit_url = f"https://docs.google.com/forms/d/{form_id}/edit"
    responder_url = created_form.get("responderUri", f"https://docs.google.com/forms/d/{form_id}/viewform")
    
    if questions:
        logger.info(f"Adding {len(questions)} questions to form {form_id}.")
        question_requests = _build_question_requests(questions)
        batch_update_body = {"requests": question_requests}
        
        try:
            await asyncio.to_thread(
                service.forms().batchUpdate(formId=form_id, body=batch_update_body).execute
            )
            logger.info(f"Successfully added questions to form {form_id}.")
        except HttpError as e:
            logger.error(f"Failed to add questions to form {form_id}: {e}")
            # Continue with form creation confirmation even if questions failed
            confirmation_message = f"Successfully created form '{created_form.get('info', {}).get('title', title)}' for {user_google_email}. Form ID: {form_id}. Edit URL: {edit_url}. Responder URL: {responder_url}. WARNING: Failed to add questions due to an error: {e}"
            return confirmation_message

    confirmation_message = f"Successfully created form '{created_form.get('info', {}).get('title', title)}' for {user_google_email}. Form ID: {form_id}. Edit URL: {edit_url}. Responder URL: {responder_url}"
    logger.info(f"Form created successfully for {user_google_email}. ID: {form_id}")
    return confirmation_message

def _build_question_requests(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Helper function to convert simplified question schema to Google Forms API Request objects.
    """
    requests = []
    for i, q in enumerate(questions):
        question_type = q.get("type")
        question_title = q.get("title")
        question_description = q.get("description")
        question_required = q.get("required", False)

        item = {
            "title": question_title,
            "description": question_description,
            "questionItem": {
                "question": {
                    "required": question_required
                }
            }
        }

        if question_type == "TEXT_QUESTION":
            item["questionItem"]["question"]["textQuestion"] = {}
        elif question_type == "MULTIPLE_CHOICE_QUESTION":
            options = q.get("options", [])
            item["questionItem"]["question"]["choiceQuestion"] = {
                "type": "RADIO",
                "options": [{"value": opt} for opt in options]
            }
        elif question_type == "SCALE_QUESTION":
            scale_min = q.get("scale_min")
            scale_max = q.get("scale_max")
            scale_labels = q.get("scale_labels", {})
            item["questionItem"]["question"]["scaleQuestion"] = {
                "low": scale_min,
                "high": scale_max,
                "lowLabel": scale_labels.get(str(scale_min)),
                "highLabel": scale_labels.get(str(scale_max))
            }
        elif question_type == "CHECKBOX_QUESTION":
            options = q.get("options", [])
            item["questionItem"]["question"]["choiceQuestion"] = {
                "type": "CHECKBOX",
                "options": [{"value": opt} for opt in options]
            }
        elif question_type == "DATE_QUESTION":
            include_time = q.get("include_time", False)
            include_year = q.get("include_year", True)
            item["questionItem"]["question"]["dateQuestion"] = {
                "includeTime": include_time,
                "includeYear": include_year
            }
        elif question_type == "TIME_QUESTION":
            item["questionItem"]["question"]["timeQuestion"] = {}
        else:
            logger.warning(f"Unsupported question type: {question_type}. Skipping question: {question_title}")
            continue

        requests.append({
            "createItem": {
                "item": item,
                "location": {
                    "index": i # Add questions sequentially
                }
            }
        })
    return requests


@server.tool()
@require_google_service("forms", "forms")
@handle_http_errors("get_form")
async def get_form(
    service,
    user_google_email: str,
    form_id: str
) -> str:
    """
    Get a form.

    Args:
        user_google_email (str): The user's Google email address. Required.
        form_id (str): The ID of the form to retrieve.

    Returns:
        str: Form details including title, description, questions, and URLs.
    """
    logger.info(f"[get_form] Invoked. Email: '{user_google_email}', Form ID: {form_id}")

    form = await asyncio.to_thread(
        service.forms().get(formId=form_id).execute
    )

    form_info = form.get("info", {})
    title = form_info.get("title", "No Title")
    description = form_info.get("description", "No Description")
    document_title = form_info.get("documentTitle", title)
    
    edit_url = f"https://docs.google.com/forms/d/{form_id}/edit"
    responder_url = form.get("responderUri", f"https://docs.google.com/forms/d/{form_id}/viewform")
    
    items = form.get("items", [])
    questions_summary = []
    for i, item in enumerate(items, 1):
        item_title = item.get("title", f"Question {i}")
        item_type = item.get("questionItem", {}).get("question", {}).get("required", False)
        required_text = " (Required)" if item_type else ""
        questions_summary.append(f"  {i}. {item_title}{required_text}")
    
    questions_text = "\n".join(questions_summary) if questions_summary else "  No questions found"
    
    result = f"""Form Details for {user_google_email}:
- Title: "{title}"
- Description: "{description}"
- Document Title: "{document_title}"
- Form ID: {form_id}
- Edit URL: {edit_url}
- Responder URL: {responder_url}
- Questions ({len(items)} total):
{questions_text}"""
    
    logger.info(f"Successfully retrieved form for {user_google_email}. ID: {form_id}")
    return result


@server.tool()
@require_google_service("forms", "forms")
@handle_http_errors("set_publish_settings")
async def set_publish_settings(
    service,
    user_google_email: str,
    form_id: str,
    publish_as_template: bool = False,
    require_authentication: bool = False
) -> str:
    """
    Updates the publish settings of a form.

    Args:
        user_google_email (str): The user's Google email address. Required.
        form_id (str): The ID of the form to update publish settings for.
        publish_as_template (bool): Whether to publish as a template. Defaults to False.
        require_authentication (bool): Whether to require authentication to view/submit. Defaults to False.

    Returns:
        str: Confirmation message of the successful publish settings update.
    """
    logger.info(f"[set_publish_settings] Invoked. Email: '{user_google_email}', Form ID: {form_id}")

    settings_body = {
        "publishAsTemplate": publish_as_template,
        "requireAuthentication": require_authentication
    }

    await asyncio.to_thread(
        service.forms().setPublishSettings(formId=form_id, body=settings_body).execute
    )

    confirmation_message = f"Successfully updated publish settings for form {form_id} for {user_google_email}. Publish as template: {publish_as_template}, Require authentication: {require_authentication}"
    logger.info(f"Publish settings updated successfully for {user_google_email}. Form ID: {form_id}")
    return confirmation_message


@server.tool()
@require_google_service("forms", "forms")
@handle_http_errors("get_form_response")
async def get_form_response(
    service,
    user_google_email: str,
    form_id: str,
    response_id: str
) -> str:
    """
    Get one response from the form.

    Args:
        user_google_email (str): The user's Google email address. Required.
        form_id (str): The ID of the form.
        response_id (str): The ID of the response to retrieve.

    Returns:
        str: Response details including answers and metadata.
    """
    logger.info(f"[get_form_response] Invoked. Email: '{user_google_email}', Form ID: {form_id}, Response ID: {response_id}")

    response = await asyncio.to_thread(
        service.forms().responses().get(formId=form_id, responseId=response_id).execute
    )

    response_id = response.get("responseId", "Unknown")
    create_time = response.get("createTime", "Unknown")
    last_submitted_time = response.get("lastSubmittedTime", "Unknown")
    
    answers = response.get("answers", {}))
    answer_details = []
    for question_id, answer_data in answers.items():
        question_response = answer_data.get("textAnswers", {}).get("answers", [])
        if question_response:
            answer_text = ", ".join([ans.get("value", "") for ans in question_response])
            answer_details.append(f"  Question ID {question_id}: {answer_text}")
        else:
            answer_details.append(f"  Question ID {question_id}: No answer provided")
    
    answers_text = "\n".join(answer_details) if answer_details else "  No answers found"
    
    result = f"""Form Response Details for {user_google_email}:
- Form ID: {form_id}
- Response ID: {response_id}
- Created: {create_time}
- Last Submitted: {last_submitted_time}
- Answers:
{answers_text}"""
    
    logger.info(f"Successfully retrieved response for {user_google_email}. Response ID: {response_id}")
    return result


@server.tool()
@require_google_service("forms", "forms")
@handle_http_errors("list_form_responses")
async def list_form_responses(
    service,
    user_google_email: str,
    form_id: str,
    page_size: int = 10,
    page_token: Optional[str] = None
) -> str:
    """
    List a form's responses.

    Args:
        user_google_email (str): The user's Google email address. Required.
        form_id (str): The ID of the form.
        page_size (int): Maximum number of responses to return. Defaults to 10.
        page_token (Optional[str]): Token for retrieving next page of results.

    Returns:
        str: List of responses with basic details and pagination info.
    """
    logger.info(f"[list_form_responses] Invoked. Email: '{user_google_email}', Form ID: {form_id}")

    params = {
        "formId": form_id,
        "pageSize": page_size
    }
    if page_token:
        params["pageToken"] = page_token

    responses_result = await asyncio.to_thread(
        service.forms().responses().list(**params).execute
    )

    responses = responses_result.get("responses", [])
    next_page_token = responses_result.get("nextPageToken")
    
    if not responses:
        return f"No responses found for form {form_id} for {user_google_email}."

    response_details = []
    for i, response in enumerate(responses, 1):
        response_id = response.get("responseId", "Unknown")
        create_time = response.get("createTime", "Unknown")
        last_submitted_time = response.get("lastSubmittedTime", "Unknown")
        
        answers_count = len(response.get("answers", {}))
        response_details.append(
            f"  {i}. Response ID: {response_id} | Created: {create_time} | Last Submitted: {last_submitted_time} | Answers: {answers_count}"
        )

    pagination_info = f"\nNext page token: {next_page_token}" if next_page_token else "\nNo more pages."
    
    result = f"""Form Responses for {user_google_email}:
- Form ID: {form_id}
- Total responses returned: {len(responses)}
- Responses:
{chr(10).join(response_details)}{pagination_info}"""
    
    logger.info(f"Successfully retrieved {len(responses)} responses for {user_google_email}. Form ID: {form_id}")
    return result
