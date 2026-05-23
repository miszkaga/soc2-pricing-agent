import os
from web_researcher import WebResearcher
from silnik_wyceny import AuditsolutionsPricingV2
import base64
import psycopg2
import json
import time
from dotenv import load_dotenv
from email.message import EmailMessage

# Biblioteki Google (Gmail)
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Biblioteki AI (LangChain / LangGraph)
from typing import TypedDict, Optional, List
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END

# Ładowanie zmiennych środowiskowych (.env)
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
DB_CONFIG = {
    "dbname": "soc2_agent",
    "user": "admin",
    "password": "password123",
    "host": "db",      # Ustawione dla Dockera
    "port": "5432"     # Ustawione dla Dockera
}

# ==========================================
# 2. DEFINICJA AGENTA (LANGGRAPH & PYDANTIC)
# ==========================================

class Soc2Extraction(BaseModel):
    # --- BEZPIECZNE DANE (z maila) ---
    liczba_pracownikow: Optional[int] = Field(description="Liczba pracowników. Zwróć null, jeśli brak w tekście.")
    infrastruktura: Optional[str] = Field(description="Dostawca chmury (np. AWS, Azure) lub On-premise/Hybryda. Zwróć null, jeśli brak.")
    dodatkowe_domeny: Optional[List[str]] = Field(description="Dodatkowe obszary SOC 2 poza Security (Availability, Confidentiality, Processing Integrity, Privacy). Zwróć puste jeśli wprost odrzucono, null jeśli w ogóle nie wspomniano.")
    typ_audytu_zapytanie: Optional[List[str]] = Field(description="O co pyta klient? Np. ['Type 1'] lub ['Type 1', 'Type 2']. Zwróć null, jeśli brak.")
    posiada_iso27001: Optional[bool] = Field(description="Czy organizacja posiada certyfikat ISO 27001? True/False/null.")
    korzysta_z_narzedzi_compliance: Optional[bool] = Field(description="Czy wspomina o narzędziach typu Vanta, Drata? True/False/null.")
    # --- DANE "Ciche" (z nagłówków) ---
    domena_firmowa: Optional[str] = Field(description="Domena firmy wyciągnięta z adresu e-mail nadawcy lub stopki (np. szybkitom.pl).")

class ResearchPlan(BaseModel):
    nazwa_firmy: str = Field(description="Zidentyfikowana nazwa firmy na podstawie maila/domeny.")
    zebrane_zmienne: List[str] = Field(description="Lista parametrów, które z sukcesem wyciągnięto z maila (np. 'liczba_pracownikow', 'chmura', 'iso27001').")
    brakujace_zmienne: List[str] = Field(description="Lista parametrów z silnika wyceny, których musimy poszukać w sieci (np. 'branza', 'kraj_centrali', 'jezyk_glowny', 'strefa_czasowa_utc_offset', 'kultura_biznesowa').")
    zapytania_wyszukiwarki: List[str] = Field(description="3-4 precyzyjne zapytania do wyszukiwarki Google, które pozwolą znaleźć brakujące dane.")

class AgentState(TypedDict):
    email_content: str
    extracted_data: Optional[Soc2Extraction]
    research_data: Optional[dict]
    draft_response: Optional[str]
    pricing_data: Optional[dict]

def extraction_node(state: AgentState):
    print("🤖 Agent czyta e-mail i wyciąga bezpieczne dane...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    structured_llm = llm.with_structured_output(Soc2Extraction)
    prompt = f"Wyciągnij kluczowe informacje z tego wątku. Szukaj uważnie:\n\n{state['email_content']}"
    result = structured_llm.invoke(prompt)
    return {"extracted_data": result}

def responder_node(state: AgentState):
    print("✍️ Brakuje bezpiecznych danych. Komponuję niezobowiązujące pytania...")
    data = state['extracted_data']
    missing_questions = []

    if data.liczba_pracownikow is None:
        missing_questions.append("- Jaka jest szacunkowa wielkość Państwa zespołu (liczba pracowników/współpracowników)?")
    if data.infrastruktura is None:
        missing_questions.append("- W jakim środowisku utrzymywana jest Państwa aplikacja (np. w 100% chmura AWS/Azure, czy posiadają Państwo własne serwery)?")
    if data.dodatkowe_domeny is None:
        missing_questions.append("- Czy docelowy audyt ma objąć wyłącznie domenę Security, czy również dodatkowe kryteria (np. Availability, Confidentiality)?")
    if data.typ_audytu_zapytanie is None:
        missing_questions.append("- Jaki typ raportu Państwa interesuje na początek: Type 1 (punkt w czasie) czy od razu Type 2 (okres obserwacji)?")
    if data.posiada_iso27001 is None:
        missing_questions.append("- Czy posiadają Państwo wdrożony system zarządzania bezpieczeństwem (np. certyfikat ISO 27001)?")
    if data.korzysta_z_narzedzi_compliance is None:
        missing_questions.append("- Czy korzystają Państwo (lub planują wdrożenie) platform automatyzujących compliance, takich jak Vanta czy Drata?")

    questions_text = "\n".join(missing_questions)

    draft = f"""Dzień dobry,

Dziękujemy za kontakt i zainteresowanie naszymi usługami. Aby móc rzetelnie oszacować pracochłonność audytu SOC 2 i przygotować dla Państwa dedykowaną wycenę, potrzebujemy uzupełnić kilka informacji technicznych o Państwa środowisku.

Prosimy o krótkie odpowiedzi na poniższe pytania:
{questions_text}

Po otrzymaniu tych informacji, niezwłocznie prześlemy kalkulację kosztów.

Z poważaniem,
Zespół Auditsolutions
"""
    return {"draft_response": draft}

def research_node(state: AgentState):
    domena = state['extracted_data'].domena_firmowa or "nieznana"
    print(f"\n🕵️‍♂️ Faza 1: Planowanie OSINT dla: {domena}")

    # A. Tworzymy plan (tak jak wcześniej)
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    structured_llm = llm.with_structured_output(ResearchPlan)

    plan_prompt = f"""
    Zidentyfikuj firmę dla domeny {domena}. 
    Stwórz 3-4 zapytania do wyszukiwarki, aby znaleźć jej branżę, kraj, język, strefę czasową, kulturę biznesową oraz przychody.
    Dane z maila: {state['extracted_data'].model_dump_json()}
    """
    plan = structured_llm.invoke(plan_prompt)

    # B. Wywołujemy OSOBNY skrypt do przeszukania sieci (To jest nowość!)
    researcher = WebResearcher()
    found_data = researcher.search_and_analyze(plan.nazwa_firmy, plan.zapytania_wyszukiwarki)

    print(f"✅ OSINT zakończony. Branża: {found_data['branza']}, Przychody: {found_data['szacowane_przychody_mln_usd']}M")

    # Przekazujemy found_data do research_data – teraz Pricer będzie miał na czym pracować!
    return {"research_data": found_data}

def pricing_node(state: AgentState):
    # Generuje wycenę wstępną na podstawie danych z maila i OSINT
    data = state['extracted_data']
    research = state.get('research_data') or {}

    pricer = AuditsolutionsPricingV2()
    pricing = pricer.calculate(data, research)

    def format_usd(value: float) -> str:
        return f"${value:,.0f}"

    areas_lines = []
    for area in pricing["areas"]:
        areas_lines.append(
            f"- {area['label']}: {format_usd(area['min_usd'])}–{format_usd(area['max_usd'])} "
            f"(szacunek: {format_usd(area['estimate_usd'])})"
        )

    factor_notes = pricing.get("x_factor_notes") or []
    factor_notes_text = "\n".join(f"- {note}" for note in factor_notes) if factor_notes else "- brak istotnych korekt"

    audit_type = ", ".join(data.typ_audytu_zapytanie) if data and data.typ_audytu_zapytanie else "nie podano"

    draft = f"""[WYCENA WSTĘPNA SOC 2]
Zakres obszarów: {", ".join(area['label'] for area in pricing["areas"])}
Typ raportu (z maila): {audit_type}

Współczynnik X: {pricing['x_factor']}
Uzasadnienie X:
{factor_notes_text}

Rozbicie obszarów:
{chr(10).join(areas_lines)}

Suma wstępna: {format_usd(pricing['total_estimate_usd'])}
Zakres sumaryczny: {format_usd(pricing['total_min_usd'])}–{format_usd(pricing['total_max_usd'])}

Uwagi:
- Security jest zawsze obowiązkowe (baseline).
- Każdy obszar jest liczony w ramach ustalonych widełek.
"""

    return {"draft_response": draft, "pricing_data": pricing}

def routing_logic(state: AgentState):
    data = state['extracted_data']
    if (data and
            data.liczba_pracownikow is not None and
            data.infrastruktura is not None and
            data.dodatkowe_domeny is not None and
            data.typ_audytu_zapytanie is not None and
            data.posiada_iso27001 is not None and
            data.korzysta_z_narzedzi_compliance is not None):
        return "go_research"
    else:
        return "ask_more"

workflow = StateGraph(AgentState)
workflow.add_node("extractor", extraction_node)
workflow.add_node("responder", responder_node)
workflow.add_node("researcher", research_node)
workflow.add_node("pricer", pricing_node)

workflow.set_entry_point("extractor")
workflow.add_conditional_edges("extractor", routing_logic, {
    "ask_more": "responder",
    "go_research": "researcher"
})
workflow.add_edge("responder", END)
# Po research przechodzimy do pricer, aby policzyć wycenę
workflow.add_edge("researcher", "pricer")
workflow.add_edge("pricer", END)

agent_app = workflow.compile()

# ==========================================
# 3. GMAIL & BAZA DANYCH
# ==========================================

def init_db():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute('''
                CREATE TABLE IF NOT EXISTS processed_messages (
                                                                  message_id VARCHAR(255) PRIMARY KEY,
                    thread_id VARCHAR(255),
                    extracted_data JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
    conn.commit()
    cur.close()
    conn.close()

def is_message_processed(message_id):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT message_id FROM processed_messages WHERE message_id = %s", (message_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result is not None

def mark_message_as_processed(message_id, thread_id, extracted_data):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    json_data = json.dumps(extracted_data.model_dump()) if extracted_data else '{}'
    cur.execute(
        "INSERT INTO processed_messages (message_id, thread_id, extracted_data) VALUES (%s, %s, %s)",
        (message_id, thread_id, json_data)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_gmail_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def create_gmail_draft(service, thread_id, body_text):
    thread = service.users().threads().get(userId='me', id=thread_id).execute()
    original_msg = thread['messages'][-1]

    headers = original_msg['payload']['headers']
    to_email = next((h['value'] for h in headers if h['name'] == 'From'), "")
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "Re: Zapytanie SOC 2")

    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    message = EmailMessage()
    message.set_content(body_text)
    message['To'] = to_email
    message['Subject'] = subject
    message['In-Reply-To'] = original_msg['id']
    message['References'] = original_msg['id']

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'message': {'threadId': thread_id, 'raw': encoded_message}}

    service.users().drafts().create(userId='me', body=create_message).execute()
    print(f"📝 Utworzono szkic na koncie Gmail dla: {to_email}")

def get_unread_emails():
    service = get_gmail_service()
    print("Szukam nieprzeczytanych wiadomości...")

    query = 'is:unread (from:user@example.com OR from:miszkaga@gmail.com)'
    results = service.users().messages().list(userId='me', q=query, maxResults=3).execute()
    messages = results.get('messages', [])

    if not messages:
        print('Brak nowych wiadomości.')
        return

    for msg in messages:
        message_id = msg['id']
        message = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        thread_id = message['threadId']

        if is_message_processed(message_id):
            print(f"Pominęto wiadomość {message_id} - już istnieje w bazie.")
            continue

        payload = message['payload']
        headers = payload.get('headers')
        subject = next((header['value'] for header in headers if header['name'] == 'Subject'), "Brak tematu")

        body = ""
        thread_data = service.users().threads().get(userId='me', id=thread_id).execute()

        for m in thread_data['messages']:
            p = m['payload']
            if 'parts' in p:
                for part in p['parts']:
                    if part['mimeType'] == 'text/plain':
                        data = part['body'].get('data')
                        if data:
                            body += base64.urlsafe_b64decode(data).decode('utf-8') + "\n---\n"
                            break
            else:
                data = p['body'].get('data')
                if data:
                    body += base64.urlsafe_b64decode(data).decode('utf-8') + "\n---\n"

        print("\n" + "="*50)
        print(f"📧 NOWA WIADOMOŚĆ W WĄTKU: {subject}")
        print("="*50)

        initial_state = {
            "email_content": body.strip(),
            "extracted_data": None,
            "research_data": None,
            "draft_response": None,
            "pricing_data": None
        }

        final_state = agent_app.invoke(initial_state)
        extracted = final_state.get('extracted_data')
        draft_text = final_state.get('draft_response')

        print("\n🎯 WYNIK EKSTRAKCJI:")
        if extracted:
            print(extracted.model_dump_json(indent=2))

        if draft_text:
            print("\n" + "-"*30)
            print("Treść przygotowanego SZKICU na Gmail:")
            print(draft_text.strip())
            print("-"*30)
            create_gmail_draft(service, thread_id, draft_text)

        print("="*50 + "\n")

        mark_message_as_processed(message_id, thread_id, extracted)

if __name__ == '__main__':
    init_db()
    print("🚀 Agent uruchomiony w trybie nasłuchiwania. (Naciśnij Ctrl+C, aby zatrzymać)")

    while True:
        try:
            get_unread_emails()
            print("⏳ Zakończono sprawdzanie. Usypiam na 60 sekund...")
        except Exception as e:
            print(f"⚠️ Wystąpił błąd podczas sprawdzania poczty: {e}")
            print("⏳ Ponawiam próbę za 60 sekund...")

        time.sleep(60)