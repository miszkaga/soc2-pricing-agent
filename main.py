import os
import base64
import psycopg2
import json
import time
import logging
from dotenv import load_dotenv
from email.message import EmailMessage
from typing import Optional, List, TypedDict

# Biblioteki Google (Gmail)
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Biblioteki AI (LangChain / LangGraph)
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

# Własne moduły
from web_researcher import WebResearcher
from silnik_wyceny import AuditsolutionsPricingV2

# ==========================================
# 1. KONFIGURACJA
# ==========================================
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
# Używamy połączenia wewnątrz Dockera (host 'db')
DB_URI = os.getenv("DB_URI", "postgresql://admin:password123@db:5432/soc2_agent")
# Comma-separated list of senders whose e-mails the agent processes
ALLOWED_EMAILS = [e.strip() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()]

# ==========================================
# 2. DEFINICJA AGENTA (LANGGRAPH)
# ==========================================

class Soc2Extraction(BaseModel):
    usluga_w_zakresie: Optional[str] = Field(description="Konkretna usługa/produkt do audytu. Jeśli cała firma, wpisz 'cała firma'. null jeśli brak.")
    liczba_pracownikow: Optional[int] = Field(description="Liczba pracowników włączonych TYLKO w zakres audytu (in-scope). null jeśli brak.")
    infrastruktura: Optional[str] = Field(description="Środowisko dla audytowanej usługi: np. AWS, Azure, On-premise. null jeśli brak.")
    dodatkowe_domeny: Optional[List[str]] = Field(description="Domeny SOC 2. Jeśli klient pisze 'wszystkie', wstaw: ['Availability', 'Confidentiality', 'Processing Integrity', 'Privacy']. null jeśli brak.")
    typ_audytu_zapytanie: Optional[List[str]] = Field(description="Type 1 lub Type 2. null jeśli brak.")
    posiada_iso27001: Optional[bool] = Field(description="True/False/null")
    korzysta_z_narzedzi_compliance: Optional[bool] = Field(description="Platformy Vanta, Drata. True/False/null")
    domena_firmowa: Optional[str] = Field(description="Domena firmy np. onet.pl")
    ocena_dojrzalosci_it: Optional[int] = Field(default=5, description="Skala 1-10 z OSINT")

class AgentState(TypedDict):
    email_content: str
    extracted_data: Optional[Soc2Extraction]
    research_data: Optional[dict]
    draft_response: Optional[str]
    pricing_data: Optional[dict]

def extraction_node(state: AgentState):
    print("🤖 Agent czyta e-mail i wyciąga dane (logika domen + System Boundary)...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    structured_llm = llm.with_structured_output(Soc2Extraction)

    prompt = f"""Jesteś analitykiem biznesowym Big4 i ekspertem od audytów SOC 2.
Twoim zadaniem jest analiza zapytań ofertowych i wyciąganie z nich ustrukturyzowanych danych.

Kluczowe zasady i logika biznesowa:
1. ZAKRES AUDYTU (System Boundary): Zidentyfikuj, czy audytujemy całą firmę, czy tylko konkretną usługę/produkt.
2. PRACOWNICY: Wartość `liczba_pracownikow` ma dotyczyć TYLKO osób objętych zakresem audytu (in-scope). Jeśli korporacja ma 20 000 ludzi, ale nad audytowaną usługą pracuje 40, wpisz 40.
3. DOMENY SOC 2: Jeśli klient prosi o "wszystkie domeny" lub "pełen audyt", użyj swojej wiedzy o SOC 2 i wylistuj wszystkie 4 dodatkowe Trust Services Criteria (Availability, Confidentiality, Processing Integrity, Privacy).
4. INFRASTRUKTURA: Jeśli klient podaje technologię (np. AWS, Azure, GCP, własna serwerownia), wywnioskuj z tego środowisko.
5. DOMENA FIRMY: Zawsze próbuj zidentyfikować domenę firmy na podstawie kontekstu.

E-mail klienta:
{state['email_content']}"""

    result = structured_llm.invoke(prompt)
    return {"extracted_data": result}

    result = structured_llm.invoke(prompt)
    return {"extracted_data": result}
def responder_node(state: AgentState):
    print("✍️ Brakuje danych. Komponuję pytania uzupełniające...")
    data = state['extracted_data']
    missing = []

    if data.usluga_w_zakresie is None: missing.append("- Jakiej konkretnie usługi lub produktu ma dotyczyć audyt (czy audytujemy całą firmę, czy wybrany system)?")
    if data.liczba_pracownikow is None: missing.append("- Ile osób jest bezpośrednio zaangażowanych w utrzymanie i rozwój audytowanej usługi (tzw. zakres systemu)?")
    if data.infrastruktura is None: missing.append("- W jakim środowisku utrzymywana jest ta usługa (np. chmura publiczna, własna serwerownia)?")
    if data.dodatkowe_domeny is None: missing.append("- Czy audyt ma objąć dodatkowe kryteria (Availability, Confidentiality, Processing Integrity, Privacy)?")
    if data.typ_audytu_zapytanie is None: missing.append("- Jaki typ raportu Państwa interesuje: Type 1 czy Type 2?")
    if data.posiada_iso27001 is None: missing.append("- Czy środowisko objęte audytem posiada certyfikat ISO 27001?")
    if data.korzysta_z_narzedzi_compliance is None: missing.append("- Czy korzystają Państwo z platform takich jak Vanta/Drata?")

    questions = "\n".join(missing)
    draft = f"Dzień dobry,\n\nAby przygotować wycenę SOC 2 dla zdefiniowanego zakresu, prosimy o odpowiedzi na:\n{questions}\n\nPozdrawiamy,\nZespół Auditsolutions"
    return {"draft_response": draft}

def research_node(state: AgentState):
    domena = state['extracted_data'].domena_firmowa or "nieznana"
    print(f"🕵️‍♂️ Faza 1: Planowanie OSINT dla: {domena}")
    researcher = WebResearcher()
    found_data = researcher.search_and_analyze(domena, [f"company info, industry, revenue {domena}"])
    return {"research_data": found_data}

def pricing_node(state: AgentState):
    print("💸 Faza 3: Obliczam wycenę z zewnętrznego modułu...")
    data = state['extracted_data']
    research = state.get('research_data') or {}

    # Wstrzyknięcie danych z OSINT do modelu wyceny
    data.ocena_dojrzalosci_it = research.get('ocena', 5)

    pricer = AuditsolutionsPricingV2()
    wycena = pricer.calculate(data)

    draft = (
        f"Dzień dobry,\n\n"
        f"Na podstawie przekazanych informacji przygotowaliśmy wstępną ofertę:\n"
        f"1. Rekomendowany model: {wycena['rekomendowany_model']}\n"
        f"2. Wycena raportu Type 1: {wycena['wycena_type1_eur']} EUR netto\n"
        f"3. Orientacyjny koszt raportu Type 2: {wycena['wycena_type2_eur']} EUR netto\n\n"
        f"Czy chcieliby Państwo umówić się na spotkanie?\n\nZ poważaniem,\nZespół Auditsolutions"
    )
    return {"draft_response": draft, "pricing_data": wycena}

def routing_logic(state: AgentState):
    data = state['extracted_data']
    if (data and data.liczba_pracownikow is not None and data.infrastruktura is not None):
        return "go_research"
    return "ask_more"

# ==========================================
# 3. KOMPILACJA GRAFU Z PAMIĘCIĄ
# ==========================================
pool = ConnectionPool(DB_URI, kwargs={"autocommit": True})
checkpointer = PostgresSaver(pool)
checkpointer.setup()

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
workflow.add_edge("researcher", "pricer")
workflow.add_edge("pricer", END)

agent_app = workflow.compile(checkpointer=checkpointer)

# ==========================================
# 4. FUNKCJE BAZY DANYCH (Historia maili)
# ==========================================
def init_db():
    conn = psycopg2.connect(DB_URI)
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
    conn = psycopg2.connect(DB_URI)
    cur = conn.cursor()
    cur.execute("SELECT message_id FROM processed_messages WHERE message_id = %s", (message_id,))
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res is not None

def mark_message_as_processed(message_id, thread_id, extracted_data):
    conn = psycopg2.connect(DB_URI)
    cur = conn.cursor()
    json_data = json.dumps(extracted_data.model_dump()) if extracted_data else '{}'
    cur.execute(
        "INSERT INTO processed_messages (message_id, thread_id, extracted_data) VALUES (%s, %s, %s)",
        (message_id, thread_id, json_data)
    )
    conn.commit()
    cur.close()
    conn.close()

# ==========================================
# 5. GMAIL API I PĘTLA NASŁUCHUJĄCA
# ==========================================
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
    try:
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
    except Exception as e:
        print(f"⚠️ Błąd podczas tworzenia draftu: {e}")

def get_unread_emails():
    service = get_gmail_service()
    print("🔍 Szukam nieprzeczytanych wiadomości...")

    query = 'is:unread (' + ' OR '.join([f'from:{e}' for e in ALLOWED_EMAILS]) + ')'
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
        print("🤖 Uruchamiam LangGraph...")

        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {
            "email_content": body.strip(),
            "extracted_data": None,
            "research_data": None,
            "draft_response": None,
            "pricing_data": None
        }

        final_state = agent_app.invoke(initial_state, config=config)
        extracted = final_state.get('extracted_data')
        draft_text = final_state.get('draft_response')

        print("\n🎯 WYNIK EKSTRAKCJI:")
        if extracted:
            print(extracted.model_dump_json(indent=2))

        if draft_text:
            print("\n" + "-"*30)
            print("Treść przygotowanego SZKICU:")
            print(draft_text.strip())
            print("-" * 30)
            create_gmail_draft(service, thread_id, draft_text)

        print("="*50 + "\n")
        mark_message_as_processed(message_id, thread_id, extracted)

if __name__ == '__main__':
    init_db()
    print("🚀 Agent uruchomiony w trybie nasłuchiwania. (Naciśnij Ctrl+C, aby zatrzymać)")
    while True:
        try:
            get_unread_emails()
            print("⏳ Zakończono sprawdzanie. Usypiam na 60 sekund...\n")
        except Exception as e:
            logging.error(f"⚠️ Błąd: {e}")
            print("⏳ Ponawiam próbę za 60 sekund...\n")
        time.sleep(60)