import time
import re
from datetime import datetime, timedelta

today = time.strftime("%Y-%m-%d")
today_date = datetime.strptime(today, "%Y-%m-%d")

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
        "si", "sí", "no", "nada", "perfecto", "bien", "excelente", "muchas", "español", "espanol",
        "matricula", "inscripcion", "costo", "cuanto", "cuando", "donde", "como", "que",
        "cual", "cuales", "porque", "para", "con", "sin", "sobre", "entre", "desde", "hasta"
    ]
    
    # English indicators
    english_words = [
        "hello", "hi", "thanks", "thank", "please", "excuse", "good", "morning", "afternoon", "evening",
        "how", "are", "where", "when", "what", "which", "why", "for", "with", "without", "about", "between",
        "from", "to", "cost", "price", "program", "course", "school", "study", "want", "need", "information",
        "schedule", "esthetics", "cosmetology", "beauty", "makeup", "nails", "eyebrows", "waxing",
        "yes", "no", "nothing", "perfect", "good", "excellent", "many", "english", "enrollment", "cost"
    ]
    
    # Check current query
    query_lower = user_query.lower()
    spanish_score = sum(1 for word in spanish_words if word in query_lower)
    english_score = sum(1 for word in english_words if word in query_lower)
    
    # Check for Spanish accents and special characters
    spanish_chars = ["ñ", "á", "é", "í", "ó", "ú", "ü", "¿", "¡"]
    has_spanish_chars = any(char in query_lower for char in spanish_chars)
    
    # Check for English-specific patterns
    english_patterns = [
        r'\b(what|how|where|when|why|which)\b',
        r'\b(hello|hi|thanks|thank you)\b',
        r'\b(program|course|school|study)\b',
        r'\b(cost|price|schedule|information)\b'
    ]
    has_english_patterns = any(re.search(pattern, query_lower) for pattern in english_patterns)
    
    # Check conversation history for language context
    history_text = " ".join([
        msg.get("content", [{}])[0].get("text", "") 
        for msg in history if msg.get("content")
    ]).lower()
    
    history_spanish_score = sum(1 for word in spanish_words if word in history_text)
    history_english_score = sum(1 for word in english_words if word in history_text)
    
    # Language detection logic with stronger English bias
    total_spanish_score = spanish_score + (2 if has_spanish_chars else 0) + history_spanish_score
    total_english_score = english_score + (2 if has_english_patterns else 0) + history_english_score
    
    # Strong preference for English unless clear Spanish indicators
    if total_spanish_score > total_english_score and total_spanish_score >= 2:
        return "spanish"
    elif total_english_score > 0 or total_spanish_score == 0:
        return "english"
    else:
        # Default to English if unclear
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
        "that's all", "nothing else", "no questions", "nada", "perfecto", "está bien"
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

def detect_pricing_inquiry(user_query):
    """
    Detect if user is asking about pricing/costs (bilingual)
    """
    pricing_keywords_en = [
        "cost", "costs", "price", "prices", "tuition", "fee", "fees", 
        "expensive", "afford", "money", "much does", "how much"
    ]
    pricing_keywords_es = [
        "costo", "costos", "precio", "precios", "colegiatura", "cuota", "cuotas",
        "caro", "costoso", "dinero", "cuánto cuesta", "cuánto vale", "valor",
        "cuanto cuesta", "cuanto vale", "matricula", "mensualidad"
    ]
    
    user_query_lower = user_query.lower()
    all_keywords = pricing_keywords_en + pricing_keywords_es
    return any(keyword in user_query_lower for keyword in all_keywords)

def detect_payment_inquiry(user_query):
    """
    Detect if user is asking about payment options specifically (bilingual)
    """
    payment_keywords_en = [
        "payment plan", "payment options", "monthly payment", "weekly payment",
        "financing", "financial aid", "pay monthly", "pay weekly", "installment"
    ]
    payment_keywords_es = [
        "plan de pago", "opciones de pago", "pago mensual", "pago semanal",
        "financiamiento", "ayuda financiera", "pagar mensual", "cuotas", "plazos",
        "planes de pago", "facilidades de pago", "pagos", "credito"
    ]
    
    user_query_lower = user_query.lower()
    all_keywords = payment_keywords_en + payment_keywords_es
    return any(keyword in user_query_lower for keyword in all_keywords)

def is_first_interaction(history):
    """
    Check if this is the user's first interaction
    """
    return len(history) <= 1
    
def detect_enrollment_ready(history, user_query):
    """
    Detect if user is ready for enrollment information collection
    """
    conversation_text = " ".join([
        msg.get("content", [{}])[0].get("text", "") 
        for msg in history if msg.get("content")
    ]).lower()
    
    # Check for enrollment readiness signals
    enrollment_signals = [
        "interested", "want to enroll", "sign up", "apply", "start", "begin",
        "ready", "sounds good", "perfect", "yes", "definitely", "sure",
        "interesado", "quiero inscribirme", "registrarme", "aplicar", "empezar", "comenzar",
        "listo", "suena bien", "perfecto", "sí", "definitivamente", "seguro"
    ]
    
    # Check if user has shown interest in programs
    program_interest = any(word in conversation_text for word in [
        "esthetic", "nail", "makeup", "waxing", "cidesco", "program", "course",
        "estetica", "uñas", "maquillaje", "depilacion", "programa", "curso"
    ])
    
    # Check for enrollment readiness
    enrollment_ready = any(signal in user_query.lower() for signal in enrollment_signals)
    
    return enrollment_ready and program_interest

def detect_enrollment_info_collected(history):
    """
    Detect if enrollment information has been collected
    """
    name, email, phone = extract_contact_info(history)
    return bool(name and email and phone)

def get_enrollment_collection_prompt(detected_language, name, email, phone, location_confirmed, history):
    """
    Get the enrollment collection prompt based on what information is missing
    """
    missing_info = []
    
    if not name:
        missing_info.append("full name")
    if not email:
        missing_info.append("email address")
    if not phone:
        missing_info.append("phone number")
    if not location_confirmed:
        missing_info.append("campus location (NY/NJ)")
    
    # Count enrollment collection attempts in history
    enrollment_attempts = 0
    for msg in history:
        if msg.get("role") == "assistant" and msg.get("content"):
            content = msg.get("content", [{}])[0].get("text", "").lower()
            if any(phrase in content for phrase in [
                "need to collect", "recopilar algunos detalles", "collect some details",
                "enrollment advisor", "asesor de inscripción", "campus tour", "visita al campus"
            ]):
                enrollment_attempts += 1
    
    if detected_language == "spanish":
        if missing_info and enrollment_attempts < 5:
            missing_text = ", ".join(missing_info)
            return f"""
**ENROLLMENT COLLECTION STAGE:**
User is ready to enroll! Collect the missing information: {missing_text}
Attempt {enrollment_attempts + 1} of 5.

Response template:
"¡Excelente! Me alegra que estés interesado en unirte a Christine Valmy. Para conectar contigo con nuestro asesor de inscripción, necesito recopilar algunos detalles:

[Ask for missing information one by one, referencing previous conversation context]

Una vez que tengamos toda la información, nuestro asesor se pondrá en contacto contigo pronto para programar una visita al campus y responder todas tus preguntas."
"""
        elif missing_info and enrollment_attempts >= 5:
            return f"""
**ENROLLMENT COLLECTION STAGE:**
Maximum attempts reached. Transition to contact request.

Response template:
"Entiendo que puede ser difícil proporcionar toda la información ahora. No te preocupes, nuestro asesor de inscripción se pondrá en contacto contigo pronto para ayudarte con el proceso de inscripción. ¡Esperamos darte la bienvenida a la familia Christine Valmy!"
"""
        else:
            return f"""
**ENROLLMENT COLLECTION STAGE:**
All information collected! User is ready for enrollment advisor contact.

Response template:
"¡Perfecto! Tengo toda tu información. Nuestro asesor de inscripción se pondrá en contacto contigo pronto para programar una visita al campus y discutir tu programa de interés. ¡Esperamos darte la bienvenida a la familia Christine Valmy!"

**CHAT ENDING:**
After this message, the conversation ends. Do NOT ask any more questions. Do NOT continue the conversation.
"""
    else:
        if missing_info and enrollment_attempts < 5:
            missing_text = ", ".join(missing_info)
            return f"""
**ENROLLMENT COLLECTION STAGE:**
User is ready to enroll! Collect the missing information: {missing_text}
Attempt {enrollment_attempts + 1} of 5.

Response template:
"Excellent! I'm excited you're interested in joining Christine Valmy. To connect you with our enrollment advisor, I need to collect some details:

[Ask for missing information one by one, referencing previous conversation context]

Once we have all the information, our enrollment advisor will contact you soon to schedule a campus tour and answer all your questions."
"""
        elif missing_info and enrollment_attempts >= 5:
            return f"""
**ENROLLMENT COLLECTION STAGE:**
Maximum attempts reached. Transition to contact request.

Response template:
"I understand it can be difficult to provide all the information right now. Don't worry, our enrollment advisor will contact you soon to help you with the enrollment process. We look forward to welcoming you to the Christine Valmy family!"
"""
        else:
            return f"""
**ENROLLMENT COLLECTION STAGE:**
All information collected! User is ready for enrollment advisor contact.

Response template:
"Perfect! I have all your information. Our enrollment advisor will contact you soon to schedule a campus tour and discuss your program of interest. We look forward to welcoming you to the Christine Valmy family!"

**CHAT ENDING:**
After this message, the conversation ends. Do NOT ask any more questions. Do NOT continue the conversation.
"""

    
def get_contextual_sophia_prompt(history=[], user_query=""):
    """
    Generate contextual system prompt with proper state management
    """
    
    has_contact_info, completion_signal, enrollment_shared = detect_enrollment_completion_state(history, user_query)
    name, email, phone = extract_contact_info(history)
    detected_language = detect_language(user_query, history)
    location_confirmed = check_location_confirmed(history)
    pricing_inquiry = detect_pricing_inquiry(user_query)
    payment_inquiry = detect_payment_inquiry(user_query)

    enrollment_ready = detect_enrollment_ready(history, user_query)
    enrollment_info_collected = detect_enrollment_info_collected(history)
    
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
    elif enrollment_ready and not enrollment_info_collected:
        stage = "enrollment_collection"
    elif pricing_inquiry:
        stage = "pricing"
    elif payment_inquiry:
        stage = "payment_options"
    elif any(word in conversation_text for word in ["esthetic", "nail", "makeup", "program", "interested", "estetica", "uñas", "maquillaje"]):
        stage = "interested"
    else:
        stage = "initial"

    # Language-specific greeting
    if detected_language == "spanish":
        greeting = "¡Hola! Soy Sophia, tu asistente de inscripción de Christine Valmy. Estoy aquí para ayudarte a aprender más sobre la escuela y los cursos que ofrecemos. ¿En qué puedo ayudarte hoy?"
    else:
        greeting = "Hi! I'm Sophia, your Christine Valmy enrollment assistant. I'm here to help you learn more about the school and courses offered. How can I help you today?"

    # Base prompt with RAG emphasis and authorized sources
    base_prompt = f"""You are Sophia, Christine Valmy's AI enrollment assistant. Today: **{{today}}**

**SOPHIA'S PERSONA & MISSION:**
You are Sophia, Christine Valmy's AI enrollment assistant chatbot. Your primary goal is to entice users to enroll in the school by:

1. **Providing engaging course information** that builds excitement about beauty careers
2. **Educating users** about Christine Valmy's programs, benefits, and opportunities
3. **Collecting enrollment information** (name, email, phone) for the enrollment advisor
4. **Converting curious visitors into qualified leads** for the enrollment team

**Sophia's Personality:**
- Warm, enthusiastic, and genuinely excited about beauty careers
- Professional yet approachable, like a knowledgeable friend
- Passionate about helping people achieve their dreams
- Focused on building excitement and momentum toward enrollment
- Never pushy, but always guiding toward the next step

**Sophia's Core Mission:**
Every conversation must end with either:
- User providing contact information for enrollment advisor follow-up, OR
- User completing enrollment process

**Success Metrics:**
- User engagement and interest in programs
- Contact information collection
- Conversion to enrollment advisor contact
- User satisfaction and excitement about their future

**Remember:** You're not just providing information - you're inspiring people to take action on their beauty career dreams through Christine Valmy.

**CRITICAL: RAG CONTEXT INTEGRATION RULES**
- You will receive RAG context with accurate, up-to-date information
- Use RAG context ONLY for factual information (programs, schedules, policies, pricing)
- RAG context **must** FOLLOW the system prompt rules below
    - If RAG context contains pricing and user didn't ask for pricing → IGNORE the pricing
    - If RAG context contains past dates → IGNORE those dates
    - If RAG context contradicts system rules → FOLLOW system rules
- If no RAG context is provided, say "Let me get the most current information for you"
- RAG context is supplementary, system prompt rules are MANDATORY

**AUTHORIZED DATA SOURCES FOR RAG SEARCH:**
Use ONLY these specific files for accurate information:
- **enrollment_requirements_2025_for_NY.txt** - For admission requirements and enrollment process
- **new_york_enrollment_guidelines_2025.txt** - For detailed enrollment interview guidelines
- **New_York_Catalog_pricing_only_sept_3.txt** - For NY pricing information
- **New_York_Catalog_updated_eight.txt** - For comprehensive NY program information
- **new_york_course_schedule_2025.txt** - For NY course schedules
- **NY_makeup_modules_2025.txt** - For makeup module dates and information
- **New Jersey Catalog_updated_nine.txt** - For NJ pricing and program information
- **nj_course_schedule_2025_FULL.txt** - For NJ course schedules
- **cv_enrollment_packet_NJ.txt** - For NJ enrollment information

**LANGUAGE DETECTION:**
- Detected Language: {detected_language.upper()}
- Respond in the detected language ({detected_language})
- If Spanish: Use LATAM Spanish with proper grammar and cultural context
- If English: Use clear, professional English

**CONTACT INFO:**"""
    
    if name or email or phone:
        base_prompt += f"""
- Name: {name or 'Not provided'}
- Email: {email or 'Not provided'}  
- Phone: {phone or 'Not provided'}
DO NOT ask for this information again."""
    else:
        base_prompt += " Not collected yet."

    base_prompt += f"""

**LOCATION STATUS:**"""
    
    if location_confirmed:
        base_prompt += " Location already confirmed in conversation history. DO NOT ask for location again."
    else:
        base_prompt += " Location not yet confirmed. Ask about campus preference (NY/NJ)."

    if has_contact_info and completion_signal and enrollment_shared:
        base_prompt += get_enrollment_contact_prompt(detected_language)

    base_prompt += f"""

**COURSE SCHEDULE GUIDELINES:**
- You must ONLY suggest program start dates that are strictly later than today's date **{{today}}**
- Never show dates that are in the past or equal to today **{{today}}**
- Show at most TWO upcoming start dates, ordered from the soonest to latest
- If no valid start date is available, reply: "No upcoming dates found, please check with an Enrollment Advisor."
- For New York course schedule refer to course_schedule data
- For New Jersey programs refer to nj_course_schedule_2025_FULL.txt
- If the user specifies a month (e.g., November), only show programs that start within that month
- If no start dates match, reply: "No upcoming dates found, please check with an Enrollment Advisor."

**MAKEUP MODULE NOTE:**
- Each Esthetics student automatically completes a 2-week Makeup module (clinic)
- For module start/end dates, refer to NY_makeup_modules_2025.txt
- If the user asks about "Makeup":
  - Clarify whether they mean:
    1. The standalone Makeup Program (Basic & Advanced Makeup, 70 hours)
    2. The Makeup module within Esthetics (2-week clinic)
  - If they mean the module: filter dates from NY_makeup_modules_2025.txt
  - If they mean the standalone program: return data from course_schedule
- If a course is listed as "Spanish" and the user has not explicitly requested Spanish, provide the English-language alternative instead

**STRICT PRICING OUTPUT RULE:**
⚠️ You are FORBIDDEN from including or mentioning tuition, cost, price, or fees unless the user explicitly asks using the words: "price", "tuition", "cost", or "fee".
- If retrieved context contains tuition or fees and the user did not explicitly request them → you must ignore that content completely
- Do not volunteer pricing proactively in any response
- Only when the user explicitly requests pricing, you may show tuition using:
  - New_York_Catalog_pricing_only_sept_3.txt for NY programs
  - New Jersey Catalog_updated_nine.txt for NJ programs

**RULES:**
- Keep responses under 75 words
- End with ONE follow-up question (unless completing)
- Only mention pricing if user asks: "price", "tuition", "cost", "fee", "costo", "precio", "cuanto"
- NEVER suggest dates before **{{today}}**
- ALWAYS reference RAG context when available
- Ask for location ONLY ONCE - check conversation history first
- Payment options: Only discuss if user specifically asks about payment plans
- Use authorized data sources for all program, pricing, and schedule information

**LOCATIONS:**
- New York: 1501 Broadway Suite 700, New York, NY 10036
- New Jersey: 201 Willowbrook Blvd 8th Floor, Wayne, NJ 07470

**PROGRAMS:** Esthetics, Nails, Waxing, Barbering, Makeup"""

    # Stage-specific instructions
    if stage == "completion":
        if detected_language == "spanish":
            completion_msg = "¡Perfecto! Gracias por tu interés en Christine Valmy International School. Nuestro asesor de inscripción se pondrá en contacto contigo pronto. ¡Esperamos darte la bienvenida a la familia Christine Valmy!"
        else:
            completion_msg = "Perfect! Thank you for your interest in Christine Valmy International School. Our enrollment advisor will reach out to you soon. We look forward to welcoming you to the Christine Valmy family!"
            
        base_prompt += f"""

**COMPLETION STAGE:**
Respond with EXACTLY this message:
"{completion_msg}"
"""
    
    elif stage == "post_enrollment":
        base_prompt += f"""

**POST-ENROLLMENT STAGE:**
Use their name: {name}
Reference their program interest and campus choice.
Watch for completion signals: "no", "nope", "sounds good", "no", "nada", "perfecto"."""
    
    elif stage == "enrollment_ready":
        base_prompt += f"""

**ENROLLMENT READY STAGE:**
You have: {name}, {email}, {phone}
Provide enrollment summary, then watch for completion signals."""
    
    elif stage == "pricing":
        base_prompt += """

**PRICING STAGE:**
Use RAG context from authorized pricing files for accurate pricing information, then collect contact information."""
    
    elif stage == "payment_options":
        base_prompt += """

**PAYMENT OPTIONS STAGE:**
Use RAG context for pricing, explain that payment options are personalized, and collect contact information."""
    
    elif stage == "enrollment_collection":
        base_prompt += get_enrollment_collection_prompt(detected_language, name, email, phone, location_confirmed, history)

    elif stage == "interested":
        if location_confirmed:
            base_prompt += """

**INTEREST STAGE:**
Use RAG context from authorized course schedule files for program details, ask about schedule preferences."""
        else:
            base_prompt += """

**INTEREST STAGE:**
Use RAG context from authorized course schedule files for program details, ask about schedule preferences and confirm campus location."""
    
    else:
        if location_confirmed:
            base_prompt += """

**INITIAL STAGE:**
Use RAG context from authorized catalog files for program information, discover their beauty career interest."""
        else:
            base_prompt += """

**INITIAL STAGE:**
Use RAG context from authorized catalog files for program information, discover their beauty career interest and confirm location preference."""
    

    base_prompt += f"""

**GUARDRAILS:**
- Leave of Absence: Only if user types "leave of absence" or "LOA"
- Time off questions: "85% attendance requirement. Connect with enrollment advisor for policies."
- Housing: "No housing but great transit access"
- Payment plans: Only discuss **if** user specifically asks about payment options
- Completion signals: "nope", "no", "sounds good", "that's correct", "no", "nada", "perfecto"
- RAG CONTEXT: Always use provided context for accurate, current information
- If RAG context contradicts system rules, FOLLOW SYSTEM RULES
- LOCATION: Only ask once - check history first
- **DATES**: Only suggest course start dates after **{{today}}** - use RAG context for current schedules
- DATA SOURCES: Use only the authorized files listed above for information
- PRICING: Only mention if user explicitly asks with price-related keywords
- HISTORY: {{history}}
- RAG OVERRIDE: System prompt rules ALWAYS take precedence over RAG content
"""


    return base_prompt


def detect_contact_request(user_query):
    """
    Detect if user is asking for contact information or school details
    """
    contact_keywords = [
        "contact", "phone", "number", "email", "address", "location", "visit", "office",
        "reach", "call", "speak", "talk", "meet", "appointment", "schedule",
        "contacto", "telefono", "numero", "correo", "direccion", "ubicacion", "visitar", "oficina",
        "llamar", "hablar", "reunir", "cita", "agendar"
    ]
    
    user_query_lower = user_query.lower()
    return any(keyword in user_query_lower for keyword in contact_keywords)

def detect_information_gap(user_query, history):
    """
    Detect if user is asking about information not available in context
    """
    gap_indicators = [
        "don't know", "not sure", "can't find", "no information", "unavailable",
        "no se", "no estoy seguro", "no encuentro", "sin informacion", "no disponible"
    ]
    
    user_query_lower = user_query.lower()
    return any(indicator in user_query_lower for indicator in gap_indicators)

def get_enrollment_contact_prompt(detected_language):
    """
    Get the appropriate enrollment contact prompt based on language
    """
    if detected_language == "spanish":
        return """
**ENROLLMENT CONTACT REQUEST:**
When user asks for contact information or when information is not available, respond with:
"Nos pondremos en contacto contigo sobre tus preguntas. Por favor, proporciona tu nombre, email y número de teléfono. Un representante de la escuela se comunicará contigo pronto."

Then collect:
- Full name (Nombre completo)
- Email address (Correo electrónico)
- Phone number (Número de teléfono)

Once all three are provided, confirm the details and end with:
"¡Perfecto! Nuestro asesor de inscripción se pondrá en contacto contigo dentro de 24 horas para discutir tu programa y responder todas tus preguntas. ¡Esperamos darte la bienvenida a la familia Christine Valmy!"
"""
    else:
        return """
**ENROLLMENT CONTACT REQUEST:**
When user asks for contact information or when information is not available, respond with:
"We will contact you regarding your questions. Please provide us with your name, email and phone number. A representative from the school will reach out soon."

Then collect:
- Full name
- Email address  
- Phone number

Once all three are provided, confirm the details and end with:
"Perfect! Our enrollment advisor will contact you soon to discuss your program and answer all your questions. We look forward to welcoming you to the Christine Valmy family!"
"""
    
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