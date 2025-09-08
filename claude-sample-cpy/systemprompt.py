import time
import re

def detect_language(user_query, history):
    """
    Detect user's preferred language from query and history
    """
    # Spanish indicators
    spanish_words = [
        "hola", "gracias", "por favor", "disculpe", "buenos", "dias", "tardes", "noches",
        "como", "esta", "donde", "cuando", "cuanto", "cuesta", "precio", "programa",
        "curso", "escuela", "estudio", "quiero", "necesito", "informacion", "horario",
        "estetica", "cosmetologia", "belleza", "maquillaje", "uñas", "cejas", "depilacion",
        "si", "sí", "no", "nada", "perfecto", "bien", "excelente", "muchas", "español", "espanol"
    ]
    
    # Check current query
    query_lower = user_query.lower()
    spanish_score = sum(1 for word in spanish_words if word in query_lower)
    
    # Check for Spanish accents and special characters
    spanish_chars = ["ñ", "á", "é", "í", "ó", "ú", "ü"]
    has_spanish_chars = any(char in query_lower for char in spanish_chars)
    
    # Check conversation history
    history_text = " ".join([
        msg.get("content", [{}])[0].get("text", "") 
        for msg in history if msg.get("content")
    ]).lower()
    
    history_spanish_score = sum(1 for word in spanish_words if word in history_text)
    
    # Language detection logic
    if spanish_score > 0 or has_spanish_chars or history_spanish_score > 2:
        return "spanish"
    else:
        return "english"

        def check_location_confirmed(history):
    """
    Check if location has been confirmed in conversation history
    """
    conversation_text = " ".join([
        msg.get("content", [{}])[0].get("text", "") 
        for msg in history if msg.get("content")
    ]).lower()
    
    # Look for location confirmations
    location_indicators = [
        "new york", "ny", "nj", "new jersey", "wayne", "broadway",
        "1501 broadway", "201 willowbrook", "manhattan", "jersey"
    ]
    
    return any(loc in conversation_text for loc in location_indicators)

today = time.strftime("%Y-%m-%d")

def detect_enrollment_completion_state(history, user_query):
    """
    Detect if enrollment should be completed based on conversation state
    """
    conversation_text = " ".join([
        msg.get("content", [{}])[0].get("text", "") 
        for msg in history if msg.get("content")
    ]).lower()
    
    # Check if contact information has been provided
    has_contact_info = (
        "@" in conversation_text and 
        any(char.isdigit() for char in conversation_text) and
        len([c for c in conversation_text if c.isdigit()]) >= 7
    )
    
    # Check for completion signals from user
    user_query_lower = user_query.lower()
    completion_signals = [
        "nope", "no", "yes that is correct", "that's correct", 
        "sounds good", "looks good", "im good", "i'm good",
        "that's all", "nothing else", "no questions"
    ]
    
    # Check if enrollment info was shared
    enrollment_shared = "enrollment team" in conversation_text or "enrollment advisor" in conversation_text
    
    return has_contact_info, any(signal in user_query_lower for signal in completion_signals), enrollment_shared

def extract_contact_info(history):
    """
    Extract contact information from conversation history
    """
    conversation_text = " ".join([
        msg.get("content", [{}])[0].get("text", "") 
        for msg in history if msg.get("content")
    ])
    
    # Extract email
    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', conversation_text)
    email = email_match.group() if email_match else None
    
    # Extract phone
    phone_match = re.search(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', conversation_text)
    phone = phone_match.group() if phone_match else None
    
    # Extract name (basic pattern)
    name = None
    for msg in history:
        if msg.get("content"):
            text = msg['content'][0]['text']
            if "@" in text and phone and len(text.split()) <= 5:
                # Look for name in same message as contact info
                words = text.replace(email or "", "").replace(phone or "", "").split()
                for word in words:
                    if word.replace(",", "").isalpha() and len(word) > 1:
                        name = word.replace(",", "")
                        break
    
    return name, email, phone

def get_contextual_sophia_prompt(history=[], user_query=""):
    """
    Generate contextual system prompt with proper state management
    """
    
    has_contact_info, completion_signal, enrollment_shared = detect_enrollment_completion_state(history, user_query)
    name, email, phone = extract_contact_info(history)
    
    # Detect current conversation state
    conversation_text = " ".join([
        msg.get("content", [{}])[0].get("text", "") 
        for msg in history if msg.get("content")
    ]).lower()
    
    # Determine stage
    if has_contact_info and completion_signal and enrollment_shared:
        stage = "completion"
    elif has_contact_info and enrollment_shared:
        stage = "post_enrollment"
    elif has_contact_info:
        stage = "enrollment_ready"
    elif any(word in user_query.lower() for word in ["price", "cost", "tuition", "fee"]):
        stage = "pricing"
    elif any(word in conversation_text for word in ["esthetic", "nail", "makeup", "program", "interested"]):
        stage = "interested"
    else:
        stage = "initial"

    # Base prompt
    base_prompt = f"""You are Sophia, Christine Valmy's AI enrollment assistant. I am here to help you learn more about the school and courses offered. I can respond in English or Spanish, which do you prefer?" 

**CRITICAL CONTACT INFO STATE:**"""
    
    if name or email or phone:
        base_prompt += f"""
Contact Info Already Collected:
- Name: {name or 'Not provided'}
- Email: {email or 'Not provided'}  
- Phone: {phone or 'Not provided'}

**NEVER ASK FOR THIS INFORMATION AGAIN - YOU ALREADY HAVE IT!**"""

    base_prompt += f"""

**Core Rules:**
- Keep responses under 75 words
- End with ONE follow-up question (unless completing enrollment)
- Only mention pricing if user asks: "price", "tuition", "cost", "fee"
- Confirm campus location (NY/NJ) before program details
- NEVER suggest dates before {today}

**Locations:**
- New York: 1501 Broadway Suite 700, New York, NY 10036
- New Jersey: 201 Willowbrook Blvd 8th Floor, Wayne, NJ 07470

**Programs:** Esthetics (600 hrs), Nails, Waxing, CIDESCO, Makeup"""

    # Stage-specific instructions
    if stage == "completion":
        base_prompt += f"""

**COMPLETION STAGE - USER IS READY TO END CHAT:**
User has provided contact info and given completion signal. 
Respond with EXACTLY this message and nothing else:

"Perfect! Thank you for your interest in Christine Valmy International School. Our enrollment advisor will reach out to you soon. We look forward to welcoming you to the Christine Valmy family!"

Do NOT ask any more questions. Do NOT repeat information. End the conversation."""
    
    elif stage == "post_enrollment":
        base_prompt += f"""

**POST-ENROLLMENT STAGE:**
Contact info collected, enrollment process started.
- Use their name: {name}
- Reference their program interest and campus choice
- If they say "no", "nope", "sounds good" - they're ready to complete
- Watch for completion signals to end conversation"""
    
    elif stage == "enrollment_ready":
        base_prompt += f"""

**ENROLLMENT READY STAGE:**
You have contact info: {name}, {email}, {phone}
Provide enrollment summary focusing on THEIR journey, then watch for completion signals."""
    
    elif stage == "pricing":
        base_prompt += """

**PRICING STAGE:**
Share pricing, then collect contact information naturally."""
    
    elif stage == "interested":
        base_prompt += """

**INTEREST STAGE:**
Ask about schedule preferences and confirm campus location."""
    
    else:
        base_prompt += """

**INITIAL STAGE:**
Discover their beauty career interest and confirm location preference."""

    # Critical guardrails
    base_prompt += f"""

**CRITICAL GUARDRAILS:**
- Leave of Absence: ONLY discuss if user types exact phrase "leave of absence" or "LOA"
- If user asks about time off, breaks, etc: "For absences, we have an 85% attendance requirement. Connect with enrollment for specific policies."
- NEVER repeat contact information requests if already provided
- Recognize completion signals: "nope", "no", "sounds good", "that's correct"
- Housing: "We don't offer housing but great transit access"
- Payment plans: "Enrollment advisor will discuss payment options"

**CONVERSATION COMPLETION:**
When user shows completion signals after enrollment info shared, end with:
"Perfect! Thank you for your interest in Christine Valmy International School. Our enrollment advisor will reach out to you soon. We look forward to welcoming you to the Christine Valmy family!"
"""

    return base_prompt

# Export for Flask integration
def get_system_prompt_for_request(history, user_query):
    """
    Main function for Flask integration
    """
    return get_contextual_sophia_prompt(history, user_query)

# Course schedule data (keep existing)
course_schedule = {
    "year": 2025,
    "months": [
        {
            "name": "September",
            "courses": [
                { "category": "Esthetics", "program": "Esthetics Monday and Tuesday", "start_date": "2025-09-08", "end_date": "2026-06-23", "weekday": "Monday", "language": "English" },
                { "category": "Esthetics", "program": "Esthetics Part Time Evening", "start_date": "2025-09-16", "end_date": "2026-07-07", "weekday": "Tuesday", "language": "English" },
                { "category": "Esthetics", "program": "Esthetics Wednesday, Thursday and Friday", "start_date": "2025-09-17", "end_date": "2026-07-10", "weekday": "Wednesday", "language": "English" },
                { "category": "Esthetics", "program": "Esthetics Full Time", "start_date": "2025-09-22", "end_date": "2026-01-30", "weekday": "Monday", "language": "English" },
                { "category": "Nails", "program": "Nails Part Time Evening", "start_date": "2025-09-23", "end_date": "2026-01-28", "weekday": "Tuesday", "language": "English" },
                { "category": "Nails", "program": "Nails Monday and Tuesday", "start_date": "2025-09-29", "end_date": "2026-02-02", "weekday": "Monday", "language": "English" }
            ]
        },
        {
            "name": "October",
            "courses": [
                { "category": "Nails", "program": "Nails Part Time Weekend", "start_date": "2025-10-11", "end_date": "2026-02-08", "weekday": "Saturday", "language": "English" },
                { "category": "Esthetics", "program": "Esthetics Full Time", "start_date": "2025-10-22", "end_date": "2026-03-04", "weekday": "Wednesday", "language": "English" },
                { "category": "Waxing", "program": "Waxing", "start_date": "2025-10-05", "end_date": "2025-11-10", "weekday": "Sunday", "language": "English" }
            ]
        },
        {
            "name": "November",
            "courses": [
                { "category": "Esthetics", "program": "Esthetics Part Time Spanish", "start_date": "2025-11-03", "end_date": "2026-05-04", "weekday": "Monday", "language": "Spanish" },
                { "category": "Esthetics", "program": "Esthetics Monday and Tuesday", "start_date": "2025-11-17", "end_date": "2026-09-01", "weekday": "Monday", "language": "English" },
                { "category": "CIDESCO", "program": "AE CIDESCO", "start_date": "2025-11-10", "end_date": "2025-12-16", "weekday": "Monday", "language": "English" }
            ]
        },
        {
            "name": "December",
            "courses": [
                { "category": "Esthetics", "program": "Esthetics Part Time Evening", "start_date": "2025-12-01", "end_date": "2026-09-21", "weekday": "Monday", "language": "English" },
                { "category": "Esthetics", "program": "Esthetics Full Time", "start_date": "2025-12-01", "end_date": "2026-04-10", "weekday": "Monday", "language": "English" },
                { "category": "Esthetics", "program": "Esthetics Wednesday Thursday and Fridays", "start_date": "2025-12-03", "end_date": "2026-09-23", "weekday": "Wednesday", "language": "English" },
                { "category": "Nails", "program": "Nails Monday and Tuesday", "start_date": "2025-12-01", "end_date": "2026-04-07", "weekday": "Monday", "language": "English" },
                { "category": "Nails", "program": "Nails Part Time Evening", "start_date": "2025-12-01", "end_date": "2026-04-08", "weekday": "Monday", "language": "English" }
            ]
        }
    ]
}

# Backward compatibility
systemprompt = get_contextual_sophia_prompt()

# Test the system
if __name__ == "__main__":
    # Test with the actual conversation scenario
    test_history = [
        {"role": "user", "content": [{"text": "anisha b, ani@b.com, 678-9386850"}]},
        {"role": "assistant", "content": [{"text": "Thank you for your information. Our enrollment team will contact you."}]},
    ]
    
    test_queries = ["nope", "no", "yes that is correct"]
    
    for query in test_queries:
        print(f"\nQuery: '{query}'")
        prompt = get_contextual_sophia_prompt(test_history, query)
        print(f"Stage detected: completion" if "COMPLETION STAGE" in prompt else "Other stage")
        print("---")