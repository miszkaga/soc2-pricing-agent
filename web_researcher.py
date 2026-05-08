import os
from tavily import TavilyClient
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

class OSINTResults(BaseModel):
    branza: str = Field(description="Branża firmy (np. SaaS, FinTech, eCommerce).")
    kraj_centrali: str = Field(description="Główna lokalizacja firmy.")
    szacowane_przychody_mln_usd: float = Field(description="Przychód w mln USD (sama liczba). Jeśli nieznany, spróbuj oszacować na podstawie wielkości.")

class WebResearcher:
    def __init__(self):
        self.tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        self.llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    def search_and_analyze(self, company_name: str, queries: list) -> dict:
        print(f"🌐 Łączę się z Tavily dla: {company_name}...")

        aggregated_context = ""

        # 1. Wykonujemy wyszukiwanie dla każdego zapytania z planu
        for query in queries:
            search_result = self.tavily.search(query=query, search_depth="advanced", max_results=2)
            for result in search_result['results']:
                aggregated_context += f"\nŹródło: {result['url']}\nTreść: {result['content']}\n"

        # 2. Prosimy Gemini o analizę zebranych materiałów
        print("🧠 Analizuję wyniki wyszukiwania...")
        structured_llm = self.llm.with_structured_output(OSINTResults)

        prompt = f"""
        Na podstawie poniższych danych z internetu o firmie '{company_name}', 
        wyciągnij 3 parametry potrzebne do wyceny audytu.
        
        DANE Z SIECI:
        {aggregated_context}
        
        Jeśli dane o przychodach są niejasne, dokonaj inteligentnego szacunku 
        (np. 150 pracowników w branży SaaS to zwykle 15-25 mln USD przychodu).
        """

        final_data = structured_llm.invoke(prompt)
        return final_data.model_dump()