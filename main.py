import os
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
    "host": "db",
    "port": "5432"
}

# ==========================================
# 1. SILNIK WYCENY AUDITSOLUTIONS
# ==========================================
class AuditsolutionsPricing:
    def __init__(self):
        self.base_security = 18500.0
        self.domains = {
            'availability': 3900.0,
            'confidentiality': 3900.0,
            'processing integrity': 7600.0,
            'privacy': 9400.0
        }

    def calculate(self, data) -> dict:
        if data.liczba_pracownikow and data.liczba_pracownikow > 500:
            return {"status": "wycena_indywidualna"}

        base = self.base_security
        if data.posiada_iso27001:
            base = base * 0.85

        domains_sum = base
        if data.dodatkowe_domeny:
            for domain in data.dodatkowe_domeny:
                for known_domain, price in self.domains.items():
                    if known_domain in domain.lower():
                        domains_sum += price
                        break

        duration_premium = 0
        typ_audytu = (data.typ_audytu or "").lower()
        if "type ii" in typ_audytu:
            if "12" in typ_audytu:
                duration_premium = domains_sum * 0.30
            else:
                duration_premium = domains_sum * 0.15

        size_surcharge = 5000.0 if (data.liczba_pracownikow and data.liczba_pracownikow > 200) else 0

        infra_surcharge = 0
        infra = (data.infrastruktura_chmurowa or "").lower()
        if "on-premise" in infra or "hybryd" in infra:
            infra_surcharge = 4000.0

        locs = data.dodatkowe_lokalizacje_fizyczne or 0
        location_surcharge = locs * 1500.0

        total = domains_sum + duration_premium + size_surcharge + infra_surcharge + location_surcharge

        return {
            "status": "sukces",
            "total_eur": round(total, 2)
        }

# ==========================================
# 2. DEFINICJA AGENTA (LANGGRAPH & PYDANTIC)
# ==========================================

class Soc2Extraction(BaseModel):
    liczba_pracownikow: Optional[int] = Field(description="Liczba pracowników. Zwróć null, jeśli brak w tekście.")
    infrastruktura_chmurowa: Optional[str] = Field(description="Dostawca chmury (np. AWS, Azure) lub On-premise/Hybryda. Zwróć null, jeśli brak.")
    dodatkowe_lokalizacje_fizyczne: Optional[int] = Field(description="Liczba dodatkowych fizycznych biur/lokalizacji. Zwróć null, jeśli brak.")
    dodatkowe_domeny: Optional[List[str]] = Field(description="Domeny SOC 2 poza Security (np. Availability, Confidentiality, Processing Integrity, Privacy). Zwróć puste jeśli wprost odrzucono, null jeśli w ogóle nie wspomniano.")
    typ_audytu: Optional[str] = Field(description="Typ audytu: Type I, Type II 6m, Type II 12m. Zwróć null, jeśli brak.")
    posiada_iso27001: Optional[bool] = Field(description="Czy organizacja posiada certyfikat ISO 27001? True/False/null.")

class AgentState(TypedDict):
    email_content: str
    extracted_data: Optional[Soc2Extraction]
    draft_response: Optional[str]

def extraction_node(state: AgentState):
    print("🤖 Agent czyta e-mail i wyciąga dane...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    structured_llm = llm.with_structured_output(Soc2Extraction)
    prompt = f"Wyciągnij informacje do wyceny audytu SOC2. Szukaj uważnie 6 parametrów:\n\n{state['email_content']}"
    result = structured_llm.invoke(prompt)
    return {"extracted_data": result}

def responder_node(state: AgentState):
    print("✍️ Brakuje danych. Komponuję pytania z szablonu Auditsolutions...")
    data = state['extracted_data']
    missing_questions = []

    if data.liczba_pracownikow is None:
        missing_questions.append("- Jaka jest ogólna liczba pracowników/współpracowników w Państwa organizacji?")
    if data.infrastruktura_chmurowa is None:
        missing_questions.append("- Z jakiego dostawcy chmury Państwo korzystają, czy posiadają własne serwery (on-premise) / środowisko hybrydowe?")
    if data.dodatkowe_lokalizacje_fizyczne is None:
        missing_questions.append("- Czy organizacja posiada dodatkowe lokalizacje fizyczne (inne biura), które podlegają audytowi? (Prosimy podać liczbę).")
    if data.dodatkowe_domeny is None:
        missing_questions.append("- Czy potrzebują Państwo rozszerzyć bazowy audyt o dodatkowe domeny? (Availability, Confidentiality, Processing Integrity, Privacy).")
    if data.typ_audytu is None:
        missing_questions.append("- Jaki typ audytu Państwa interesuje: Type I (punkt w czasie) czy Type II (okres obserwacji np. 6 lub 12 m-cy)?")
    if data.posiada_iso27001 is None:
        missing_questions.append("- Czy organizacja posiada już certyfikat ISO/IEC 27001?")

    questions_text = "\n".join(missing_questions)

    draft = f"""Dzień dobry,

Dziękujemy za kontakt. Aby móc rzetelnie wycenić audyt SOC 2 i przygotować dla Państwa dedykowaną ofertę, potrzebujemy uzupełnić kilka kluczowych informacji o Państwa organizacji.

Prosimy o krótkie odpowiedzi na poniższe pytania:
{questions_text}

Po otrzymaniu tych informacji, niezwłocznie przygotujemy dla Państwa kompleksowy kosztorys.

Z poważaniem,
Zespół Auditsolutions
"""
    return {"draft_response": draft}

def pricing_node(state: AgentState):
    print("💶 Mamy komplet! Uruchamiam Silnik Wyceny Auditsolutions...")
    data = state['extracted_data']
    calculator = AuditsolutionsPricing()
    result = calculator.calculate(data)

    if result["status"] == "wycena_indywidualna":
        draft = "Dzień dobry,\n\nDziękujemy za przekazanie szczegółów. Z uwagi na skalę Państwa organizacji (powyżej 500 pracowników), projekt ten wymaga niestandardowego podejścia.\nNasz audytor skontaktuje się z Państwem bezpośrednio w celu ustalenia terminu krótkiego spotkania (scoping call).\n\nZ wyrazami szacunku,\nZespół Auditsolutions"
    else:
        cena = result["total_eur"]
        draft = f"Dzień dobry,\n\nDziękujemy za przekazanie wszystkich informacji. Na ich podstawie nasz system wygenerował wstępny kosztorys audytu SOC 2.\n\nSzacunkowy koszt inwestycji dla wskazanych parametrów wynosi: {cena} EUR netto.\n\n[TUTAJ DOCELOWO BĘDZIE ZALĄCZNIK PDF Z MACIERZĄ WYCENY]\n\nZ poważaniem,\nZespół Auditsolutions"

    return {"draft_response": draft}

def should_continue(state: AgentState):
    data = state['extracted_data']
    if (data and
            data.liczba_pracownikow is not None and
            data.infrastruktura_chmurowa is not None and
            data.dodatkowe_lokalizacje_fizyczne is not None and
            data.dodatkowe_domeny is not None and
            data.typ_audytu is not None and
            data.posiada_iso27001 is not None):
        return "complete"
    else:
        return "incomplete"

workflow = StateGraph(AgentState)
workflow.add_node("extractor", extraction_node)
workflow.add_node("responder", responder_node)
workflow.add_node("pricer", pricing_node)

workflow.set_entry_point("extractor")
workflow.add_conditional_edges(
    "extractor",
    should_continue,
    {
        "incomplete": "responder",
        "complete": "pricer"
    }
)
workflow.add_edge("responder", END)
workflow.add_edge("pricer", END)
agent_app = workflow.compile()

# ==========================================
# 3. GMAIL & BAZA (ZAKTUALIZOWANA LOGIKA WIADOMOŚCI)
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

    # TUTAJ DODALIŚMY FILTR: from:user@example.com
    results = service.users().messages().list(userId='me', q='is:unread from:user@example.com', maxResults=3).execute()
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
            "draft_response": None
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