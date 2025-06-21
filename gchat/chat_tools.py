"""
Google Chat MCP Tools

This module provides MCP tools for interacting with Google Chat API.
Enhanced with Card Framework integration and adapter system support.
"""
import logging
import asyncio
import json
from typing import Optional, Dict, Any, List, Union

from mcp import types
from googleapiclient.errors import HttpError

# Auth & server utilities
from auth.service_decorator import require_google_service
from core.server import server
from core.utils import handle_http_errors

# Card Framework integration
try:
    from card_framework.v2 import Message # Import Message class
    from .chat_cards_optimized import GoogleChatCardManager
    CARDS_AVAILABLE = True
except ImportError:
    CARDS_AVAILABLE = False

# Adapter system integration
try:
    from adapters import AdapterFactory, AdapterRegistry, DiscoveryManager
    ADAPTERS_AVAILABLE = True
except ImportError:
    ADAPTERS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Initialize card manager if available
if CARDS_AVAILABLE:
    card_manager = GoogleChatCardManager()
    logger.info("Google Chat Card Manager initialized")
else:
    card_manager = None
    logger.warning("Card Manager not available - cards will use fallback format")

# Initialize adapter system if available
if ADAPTERS_AVAILABLE:
    discovery_manager = DiscoveryManager()
    adapter_factory = AdapterFactory(discovery_manager)
    adapter_registry = AdapterRegistry(adapter_factory)
    logger.info("Adapter system initialized for Google Chat")
else:
    discovery_manager = None
    adapter_factory = None
    adapter_registry = None
    logger.warning("Adapter system not available")

@server.tool()
@require_google_service("chat", "chat_read")
@handle_http_errors("list_spaces")
async def list_spaces(
    service,
    user_google_email: str,
    page_size: int = 100,
    space_type: str = "all"  # "all", "room", "dm"
) -> str:
    """
    Lists Google Chat spaces (rooms and direct messages) accessible to the user.

    Returns:
        str: A formatted list of Google Chat spaces accessible to the user.
    """
    logger.info(f"[list_spaces] Email={user_google_email}, Type={space_type}")

    # Build filter based on space_type
    filter_param = None
    if space_type == "room":
        filter_param = "spaceType = SPACE"
    elif space_type == "dm":
        filter_param = "spaceType = DIRECT_MESSAGE"

    request_params = {"pageSize": page_size}
    if filter_param:
        request_params["filter"] = filter_param

    response = await asyncio.to_thread(
        service.spaces().list(**request_params).execute
    )

    spaces = response.get('spaces', [])
    if not spaces:
        return f"No Chat spaces found for type '{space_type}'."

    output = [f"Found {len(spaces)} Chat spaces (type: {space_type}):"]
    for space in spaces:
        space_name = space.get('displayName', 'Unnamed Space')
        space_id = space.get('name', '')
        space_type_actual = space.get('spaceType', 'UNKNOWN')
        output.append(f"- {space_name} (ID: {space_id}, Type: {space_type_actual})")

    return "\n".join(output)

@server.tool()
@require_google_service("chat", "chat_read")
@handle_http_errors("get_messages")
async def get_messages(
    service,
    user_google_email: str,
    space_id: str,
    page_size: int = 50,
    order_by: str = "createTime desc"
) -> str:
    """
    Retrieves messages from a Google Chat space.

    Returns:
        str: Formatted messages from the specified space.
    """
    logger.info(f"[get_messages] Space ID: '{space_id}' for user '{user_google_email}'")

    # Get space info first
    space_info = await asyncio.to_thread(
        service.spaces().get(name=space_id).execute
    )
    space_name = space_info.get('displayName', 'Unknown Space')

    # Get messages
    response = await asyncio.to_thread(
        service.spaces().messages().list(
            parent=space_id,
            pageSize=page_size,
            orderBy=order_by
        ).execute
    )

    messages = response.get('messages', [])
    if not messages:
        return f"No messages found in space '{space_name}' (ID: {space_id})."

    output = [f"Messages from '{space_name}' (ID: {space_id}):\n"]
    for msg in messages:
        sender = msg.get('sender', {}).get('displayName', 'Unknown Sender')
        create_time = msg.get('createTime', 'Unknown Time')
        text_content = msg.get('text', 'No text content')
        msg_name = msg.get('name', '')

        output.append(f"[{create_time}] {sender}:")
        output.append(f"  {text_content}")
        output.append(f"  (Message ID: {msg_name})\n")

    return "\n".join(output)

@server.tool()
@require_google_service("chat", "chat_write")
@handle_http_errors("send_message")
async def send_message(
    service,
    user_google_email: str,
    space_id: str,
    message_text: str,
    thread_key: Optional[str] = None
) -> str:
    """
    Sends a message to a Google Chat space.

    Returns:
        str: Confirmation message with sent message details.
    """
    logger.info(f"[send_message] Email: '{user_google_email}', Space: '{space_id}'")

    message_body = {
        'text': message_text
    }

    # Add thread key if provided (for threaded replies)
    request_params = {
        'parent': space_id,
        'body': message_body
    }
    if thread_key:
        request_params['threadKey'] = thread_key

    message = await asyncio.to_thread(
        service.spaces().messages().create(**request_params).execute
    )

    message_name = message.get('name', '')
    create_time = message.get('createTime', '')

    msg = f"Message sent to space '{space_id}' by {user_google_email}. Message ID: {message_name}, Time: {create_time}"
    logger.info(f"Successfully sent message to space '{space_id}' by {user_google_email}")
    return msg

@server.tool()
@require_google_service("chat", "chat_read")
@handle_http_errors("search_messages")
async def search_messages(
    service,
    user_google_email: str,
    query: str,
    space_id: Optional[str] = None,
    page_size: int = 25
) -> str:
    """
    Searches for messages in Google Chat spaces by text content.

    Returns:
        str: A formatted list of messages matching the search query.
    """
    logger.info(f"[search_messages] Email={user_google_email}, Query='{query}'")

    # If specific space provided, search within that space
    if space_id:
        response = await asyncio.to_thread(
            service.spaces().messages().list(
                parent=space_id,
                pageSize=page_size,
                filter=f'text:"{query}"'
            ).execute
        )
        messages = response.get('messages', [])
        context = f"space '{space_id}'"
    else:
        # Search across all accessible spaces (this may require iterating through spaces)
        # For simplicity, we'll search the user's spaces first
        spaces_response = await asyncio.to_thread(
            service.spaces().list(pageSize=100).execute
        )
        spaces = spaces_response.get('spaces', [])

        messages = []
        for space in spaces[:10]:  # Limit to first 10 spaces to avoid timeout
            try:
                space_messages = await asyncio.to_thread(
                    service.spaces().messages().list(
                        parent=space.get('name'),
                        pageSize=5,
                        filter=f'text:"{query}"'
                    ).execute
                )
                space_msgs = space_messages.get('messages', [])
                for msg in space_msgs:
                    msg['_space_name'] = space.get('displayName', 'Unknown')
                messages.extend(space_msgs)
            except HttpError:
                continue  # Skip spaces we can't access
        context = "all accessible spaces"

    if not messages:
        return f"No messages found matching '{query}' in {context}."

    output = [f"Found {len(messages)} messages matching '{query}' in {context}:"]
    for msg in messages:
        sender = msg.get('sender', {}).get('displayName', 'Unknown Sender')
        create_time = msg.get('createTime', 'Unknown Time')
        text_content = msg.get('text', 'No text content')
        space_name = msg.get('_space_name', 'Unknown Space')

        # Truncate long messages
        if len(text_content) > 100:
            text_content = text_content[:100] + "..."

        output.append(f"- [{create_time}] {sender} in '{space_name}': {text_content}")

    return "\n".join(output)

@server.tool()
@require_google_service("chat", "chat_write")
@handle_http_errors("send_card_message")
async def send_card_message(
    service,
    user_google_email: str,
    space_id: str,
    card_type: str = "simple",
    title: str = "",
    text: str = "",
    subtitle: Optional[str] = None,
    image_url: Optional[str] = None,
    buttons: Optional[List[Dict[str, Any]]] = None,
    fields: Optional[List[Dict[str, Any]]] = None,
    submit_action: Optional[Dict[str, Any]] = None,
    thread_key: Optional[str] = None
) -> str:
    """
    Sends a rich card message to a Google Chat space using Card Framework.
    Falls back to REST API format if Card Framework is not available.

    Args:
        user_google_email: The user's Google email address
        space_id: The space ID to send the message to
        card_type: Type of card ("simple", "interactive", "form")
        title: Card title
        text: Main text content
        subtitle: Optional subtitle for simple cards
        image_url: Optional image URL for simple cards
        buttons: List of button configurations for interactive cards
        fields: List of form field configurations for form cards
        submit_action: Submit button action for form cards
        thread_key: Optional thread key for threaded replies

    Returns:
        str: Confirmation message with sent message details
    """
    logger.info(f"[send_card_message] Email: '{user_google_email}', Space: '{space_id}', Type: '{card_type}'")

    if not card_manager:
        # Fallback to text message if card manager is not available
        fallback_text = f"{title}\n{subtitle or ''}\n{text}".strip()
        return await send_message(service, user_google_email, space_id, fallback_text, thread_key)

    # Create card based on type
    try:
        # Create a Message object to hold the card(s)
        message_obj = Message()
        logger.debug(f"[DEBUG] Message object created: {type(message_obj)}")
        logger.debug(f"[DEBUG] Message.cards_v2 type: {type(message_obj.cards_v2)}")
        logger.debug(f"[DEBUG] Message.cards_v2 value: {message_obj.cards_v2}")
        
        if text: # Add plain text if provided
            message_obj.text = text

        if card_type == "simple":
            card_obj = card_manager.create_simple_card(title, subtitle, text, image_url)
        elif card_type == "interactive":
            if not buttons:
                buttons = []
            card_dict = card_manager.create_interactive_card(title, text, buttons)
        elif card_type == "form":
            if not fields or not submit_action:
                raise ValueError("Form cards require 'fields' and 'submit_action' parameters")
            card_dict = card_manager.create_form_card(title, fields, submit_action)
        else:
            raise ValueError(f"Unsupported card type: {card_type}")

        # Append the created card object to the Message object's cards_v2 list
        # The Message.render() method will handle the final Google Chat API format.
        logger.debug(f"[DEBUG] About to append card_obj: {type(card_obj)}")
        logger.debug(f"[DEBUG] card_obj content: {card_obj}")
        logger.debug(f"[DEBUG] Checking if cards_v2 supports append: {hasattr(message_obj.cards_v2, 'append')}")
        
        try:
            message_obj.cards_v2.append(card_obj)
            logger.debug(f"[DEBUG] Successfully appended card to cards_v2")
        except Exception as append_error:
            logger.error(f"[DEBUG] Error appending to cards_v2: {append_error}")
            logger.debug(f"[DEBUG] cards_v2 dir: {dir(message_obj.cards_v2)}")
            raise
        
        # Render the message object to get the final payload
        logger.debug(f"[DEBUG] About to render message object")
        message_body = message_obj.render()
        logger.debug(f"[DEBUG] Message rendered successfully")
        
        # Fix Card Framework v2 field name issue: cards_v_2 -> cardsV2
        if "cards_v_2" in message_body:
            message_body["cardsV2"] = message_body.pop("cards_v_2")
            logger.debug(f"[DEBUG] Converted cards_v_2 to cardsV2")

    except Exception as e:
        logger.error(f"Error creating or rendering card: {e}", exc_info=True)
        fallback_text = f"{title}\n{subtitle or ''}\n{text}".strip()
        return await send_message(service, user_google_email, space_id, fallback_text, thread_key)

    # Send card message
    logger.debug(f"Sending card message with body: {json.dumps(message_body, indent=2)}")

    # Add thread key if provided
    request_params = {
        'parent': space_id,
        'body': message_body
    }
    if thread_key:
        request_params['threadKey'] = thread_key

    try:
        message = await asyncio.to_thread(
            service.spaces().messages().create(**request_params).execute
        )
        logger.debug(f"Google Chat API response: {json.dumps(message, indent=2)}")

        message_name = message.get('name', '')
        create_time = message.get('createTime', '')

        msg = f"Card message sent to space '{space_id}' by {user_google_email}. Message ID: {message_name}, Time: {create_time}, Card Type: {card_type}"
        logger.info(f"Successfully sent card message to space '{space_id}' by {user_google_email}")
        return msg

    except Exception as e:
        logger.error(f"Error sending card message: {e}", exc_info=True)
        # Fallback to text message
        fallback_text = f"{title}\n{subtitle or ''}\n{text}".strip()
        return await send_message(user_google_email=user_google_email, space_id=space_id, message_text=fallback_text, thread_key=thread_key)

@server.tool()
@handle_http_errors("send_simple_card")
async def send_simple_card(
    user_google_email: str,
    space_id: str,
    title: str,
    text: str,
    subtitle: Optional[str] = None,
    image_url: Optional[str] = None,
    thread_key: Optional[str] = None,
    webhook_url: Optional[str] = None
) -> str:
    """
    Sends a simple card message to a Google Chat space.

    Args:
        user_google_email: The user's Google email address
        space_id: The space ID to send the message to
        title: Card title
        text: Main text content
        subtitle: Optional subtitle
        image_url: Optional image URL
        thread_key: Optional thread key for threaded replies
        webhook_url: Optional webhook URL for card delivery (bypasses API restrictions)

    Returns:
        str: Confirmation message with sent message details
    """
    if webhook_url:
        # Use webhook delivery like send_rich_card
        try:
            if not card_manager:
                return "Card Framework not available. Cannot send simple cards via webhook."
            
            # Create simple card using Card Framework
            card = card_manager.create_simple_card(title, subtitle, text, image_url)
            google_format_card = card_manager._convert_card_to_google_format(card)
            
            # Create message payload
            rendered_message = {
                "text": f"Simple card: {title}",
                "cardsV2": [google_format_card]
            }
            
            # Send via webhook
            import requests
            response = requests.post(
                webhook_url,
                json=rendered_message,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                return f"✅ Simple card sent successfully via webhook! Status: {response.status_code}"
            else:
                return f"❌ Webhook delivery failed. Status: {response.status_code}, Response: {response.text}"
        except Exception as e:
            return f"Failed to send simple card via webhook: {str(e)}"
    else:
        # Fallback to text message since we don't have service parameter
        fallback_text = f"{title}\n{subtitle or ''}\n{text}".strip()
        return f"Simple card fallback (no webhook provided): {fallback_text}"

@server.tool()
@handle_http_errors("send_interactive_card")
async def send_interactive_card(
    user_google_email: str,
    space_id: str,
    title: str,
    text: str,
    buttons: List[Dict[str, Any]],
    thread_key: Optional[str] = None,
    webhook_url: Optional[str] = None
) -> str:
    """
    Sends an interactive card with buttons to a Google Chat space.

    Args:
        user_google_email: The user's Google email address
        space_id: The space ID to send the message to
        title: Card title
        text: Main text content
        buttons: List of button configurations
        thread_key: Optional thread key for threaded replies
        webhook_url: Optional webhook URL for card delivery (bypasses API restrictions)

    Returns:
        str: Confirmation message with sent message details
    """
    if webhook_url:
        # Use webhook delivery like send_rich_card
        try:
            if not card_manager:
                return "Card Framework not available. Cannot send interactive cards via webhook."
            
            # Create interactive card manually (Card Framework has button format issues)
            # Convert buttons to Google Chat format
            google_buttons = []
            for btn in buttons:
                google_btn = {
                    "text": btn.get("text", "Button")
                }
                if "url" in btn:
                    google_btn["onClick"] = {
                        "openLink": {
                            "url": btn["url"]
                        }
                    }
                elif "onClick" in btn:
                    google_btn["onClick"] = btn["onClick"]
                google_buttons.append(google_btn)
            
            # Create card structure manually
            card_dict = {
                "header": {
                    "title": title
                },
                "sections": [
                    {
                        "widgets": [
                            {
                                "textParagraph": {
                                    "text": text
                                }
                            },
                            {
                                "buttonList": {
                                    "buttons": google_buttons
                                }
                            }
                        ]
                    }
                ]
            }
            
            # Create message payload
            rendered_message = {
                "text": f"Interactive card: {title}",
                "cardsV2": [{"card": card_dict}]
            }
            
            # Send via webhook
            import requests
            response = requests.post(
                webhook_url,
                json=rendered_message,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                return f"✅ Interactive card sent successfully via webhook! Status: {response.status_code}"
            else:
                return f"❌ Webhook delivery failed. Status: {response.status_code}, Response: {response.text}"
        except Exception as e:
            return f"Failed to send interactive card via webhook: {str(e)}"
    else:
        # Fallback to text message since we don't have service parameter
        fallback_text = f"{title}\n{text}\nButtons: {', '.join([btn.get('text', 'Button') for btn in buttons])}"
        return f"Interactive card fallback (no webhook provided): {fallback_text}"

@server.tool()
@handle_http_errors("send_form_card")
async def send_form_card(
    user_google_email: str,
    space_id: str,
    title: str,
    fields: List[Dict[str, Any]],
    submit_action: Dict[str, Any],
    thread_key: Optional[str] = None,
    webhook_url: Optional[str] = None
) -> str:
    """
    Sends a form card to a Google Chat space.

    Args:
        user_google_email: The user's Google email address
        space_id: The space ID to send the message to
        title: Form title
        fields: List of form field configurations
        submit_action: Submit button action configuration
        thread_key: Optional thread key for threaded replies
        webhook_url: Optional webhook URL for card delivery (bypasses API restrictions)

    Returns:
        str: Confirmation message with sent message details
    """
    if webhook_url:
        # Use webhook delivery like send_rich_card
        try:
            if not card_manager:
                return "Card Framework not available. Cannot send form cards via webhook."
            
            # Create form card manually (Card Framework has form format issues)
            # Convert fields to Google Chat format
            google_widgets = []
            
            # Add title text
            google_widgets.append({
                "textParagraph": {
                    "text": f"<b>{title}</b>"
                }
            })
            
            # Add form fields (Note: Google Chat has limited form support)
            for field in fields:
                field_widget = {
                    "textParagraph": {
                        "text": f"<b>{field.get('label', field.get('name', 'Field'))}:</b> {field.get('type', 'text_input')}" +
                               (" (Required)" if field.get('required', False) else " (Optional)")
                    }
                }
                google_widgets.append(field_widget)
            
            # Add submit button
            submit_button = {
                "buttonList": {
                    "buttons": [
                        {
                            "text": "Submit Form",
                            "onClick": {
                                "action": submit_action
                            }
                        }
                    ]
                }
            }
            google_widgets.append(submit_button)
            
            # Create card structure manually
            card_dict = {
                "header": {
                    "title": title
                },
                "sections": [
                    {
                        "widgets": google_widgets
                    }
                ]
            }
            
            # Create message payload
            rendered_message = {
                "text": f"Form card: {title}",
                "cardsV2": [{"card": card_dict}]
            }
            
            # Send via webhook
            import requests
            response = requests.post(
                webhook_url,
                json=rendered_message,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                return f"✅ Form card sent successfully via webhook! Status: {response.status_code}"
            else:
                return f"❌ Webhook delivery failed. Status: {response.status_code}, Response: {response.text}"
        except Exception as e:
            return f"Failed to send form card via webhook: {str(e)}"
    else:
        # Fallback to text message since we don't have service parameter
        field_names = ', '.join([field.get('name', 'Field') for field in fields])
        fallback_text = f"{title}\nForm fields: {field_names}"
        return f"Form card fallback (no webhook provided): {fallback_text}"

@server.tool()
async def get_card_framework_status() -> str:
    """
    Get the status of Card Framework integration.

    Returns:
        str: Status information about Card Framework availability
    """
    if card_manager:
        status = card_manager.get_framework_status()
        return f"Card Framework Status: {status}"
    else:
        return "Card Framework Status: Not available - using fallback text messaging"

@server.tool()
async def get_adapter_system_status() -> str:
    """
    Get the status of the adapter system integration.

    Returns:
        str: Status information about adapter system availability
    """
    if ADAPTERS_AVAILABLE and adapter_registry:
        adapter_count = adapter_registry.get_adapter_count()
        adapter_names = adapter_registry.get_adapter_names()
        return f"Adapter System Status: Available - {adapter_count} adapters registered: {adapter_names}"
    else:
        return "Adapter System Status: Not available"

@server.tool()
async def list_available_card_types() -> str:
    """
    List all available card types and their descriptions.

    Returns:
        str: List of available card types
    """
    card_types = {
        "simple": "Basic card with title, text, optional subtitle and image",
        "interactive": "Card with buttons for user interaction",
        "form": "Card with input fields and submit functionality",
        "rich": "Advanced card with multiple sections, columns, decorated text, and complex layouts"
    }
    
    output = ["Available Card Types:"]
    for card_type, description in card_types.items():
        output.append(f"- {card_type}: {description}")
    
    if card_manager:
        framework_status = card_manager.get_framework_status()
        output.append(f"\nCard Framework: {'Available' if framework_status['framework_available'] else 'Fallback mode'}")
    else:
        output.append("\nCard Framework: Not available")
    
    return "\n".join(output)


@server.tool()
@require_google_service("chat", "chat_write")
async def send_rich_card(
    service,
    user_google_email: str,
    space_id: str,
    title: str = "Rich Card Test",
    subtitle: Optional[str] = None,
    image_url: Optional[str] = None,
    sections: Optional[List[Dict[str, Any]]] = None,
    thread_key: Optional[str] = None,
    webhook_url: Optional[str] = None
) -> str:
    """
    Sends a rich card message to a Google Chat space with advanced formatting.
    
    Due to Google Chat API restrictions, cards cannot be sent using human credentials.
    This tool supports two delivery methods:
    1. Webhook URL (recommended for cards) - bypasses credential restrictions
    2. Google Chat API (fallback for text-only messages)

    Args:
        user_google_email: The user's Google email address (used for API fallback)
        space_id: The space ID to send the message to (used for API fallback)
        title: Card title
        subtitle: Optional subtitle
        image_url: Optional image URL
        sections: Optional list of section configurations for advanced layouts
        thread_key: Optional thread key for threaded replies
        webhook_url: Optional webhook URL for card delivery (bypasses API restrictions)

    Returns:
        str: Confirmation message with sent message details
    """
    try:
        logger.info(f"=== RICH CARD TEST START ===")
        logger.info(f"User: {user_google_email}, Space: {space_id}, Title: {title}")
        logger.info(f"Webhook URL provided: {bool(webhook_url)}")
        
        if not card_manager:
            return "Card Framework not available. Cannot send rich cards."
        
        # Create rich card using Card Framework
        logger.info("Creating rich card with Card Framework...")
        card = card_manager.create_rich_card(
            title=title,
            subtitle=subtitle,
            image_url=image_url,
            sections=sections
        )
        
        logger.info(f"Rich card created: {type(card)}")
        
        # Convert card to proper Google format
        google_format_card = card_manager._convert_card_to_google_format(card)
        logger.info(f"Card converted to Google format: {type(google_format_card)}")
        
        # Create message payload
        rendered_message = {
            "text": f"Rich card test: {title}",
            "cardsV2": [google_format_card]
        }
        
        logger.info(f"Final payload keys: {list(rendered_message.keys())}")
        logger.debug(f"Final payload: {json.dumps(rendered_message, indent=2)}")
        
        # Choose delivery method based on webhook_url
        if webhook_url:
            # Use webhook delivery (bypasses credential restrictions)
            logger.info("Sending via webhook URL...")
            import requests
            
            response = requests.post(
                webhook_url,
                json=rendered_message,
                headers={'Content-Type': 'application/json'}
            )
            
            logger.info(f"Webhook response status: {response.status_code}")
            if response.status_code == 200:
                logger.info(f"=== RICH CARD WEBHOOK SUCCESS ===")
                return f"✅ Rich card sent successfully via webhook! Status: {response.status_code}"
            else:
                logger.error(f"Webhook failed: {response.text}")
                return f"❌ Webhook delivery failed. Status: {response.status_code}, Response: {response.text}"
        else:
            # Use Google Chat API (will fail for cards with human credentials)
            logger.info("Sending via Google Chat API...")
            logger.warning("Note: Google Chat API blocks cards with human credentials. Consider using webhook_url parameter.")
            
            # Handle space_id format - ensure it starts with "spaces/"
            if not space_id.startswith("spaces/"):
                parent_space = f"spaces/{space_id}"
            else:
                parent_space = space_id
                
            result = service.spaces().messages().create(
                parent=parent_space,
                body=rendered_message,
                threadKey=thread_key
            ).execute()
            
            logger.info(f"=== RICH CARD API SUCCESS ===")
            return f"Rich card sent successfully via API! Message ID: {result.get('name', 'Unknown')}"
        
    except Exception as e:
        logger.error(f"=== RICH CARD TEST FAILED ===")
        logger.error(f"Error sending rich card: {e}", exc_info=True)
        return f"Failed to send rich card: {str(e)}"