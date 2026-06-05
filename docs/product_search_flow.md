# Mahsulotni tender manbalaridan topish oqimi (flowchart)

Bu loyiha tender portallardan mahsulotni topishni **2 bosqich**da qiladi:

1) Query → **keywordlar** (LLM)  
2) Keywordlar → **xarid katalogidan product_code topish** → shu `product_code` bilan completed-deals’dan lotlarni olish  
   (etender’da esa `product_code` yo‘q — keyword bilan qidiradi)

Quyidagi diagramma real kod oqimini ko‘rsatadi (asosiy joylar: `app/api_server.py`, `app/services/search_orchestrator.py`, `app/connectors/*.py`).

```mermaid
flowchart TD
  U[User query] --> API[POST /api/generate\napp/api_server.py]

  API --> QUS[QueryUnderstandingService.build_search_plan\napp/services/query_understanding_service.py]
  QUS --> KW[Keywords (RU+UZ)\n+ seed keywords (original kirill / RU translit)]

  KW --> EN[enabled_sources (default 4 source)]

  EN --> XR{Xarid manbalari yoqilganmi?\n(xarid shop/national/auction)}
  XR -- Yo‘q --> ORCH[SearchOrchestrator.collect_all_sources\napp/services/search_orchestrator.py]
  XR -- Ha --> CPC[XaridUzexConnector.find_product_candidates\napp/connectors/xarid_uzex_connector.py]

  CPC --> CAT[GET https://xarid-api-trade.uzex.uz/Lib/GetCategories]
  CAT --> PROD[For each keyword × category:\nGET /Lib/GetProducts/{category_id}?keyword=...]
  PROD --> SCORE[Score + dedupe by product_code\n(top N candidates)]

  SCORE --> SEL{Candidate bormi?}
  SEL -- Yo‘q --> ORCH
  SEL -- Ha --> LLMSEL[CandidateSelectorService.select_best_candidate (LLM)\napp/services/candidate_selector_service.py]
  LLMSEL --> SP[selected_product:\nproduct_code + category_id]
  SP --> ORCH

  ORCH --> XSRC[xarid sources (shop/national/auction)]
  XSRC --> XAPI[POST https://xarid-api-*/Common/GetCompletedDeals\npayload: category_id + product_code + year_id + paging]
  XAPI --> XFILT[Filter: status paid/delivered\n+ period_months]
  XFILT --> XEV[Evidence (unit_price = deal_cost/amount if amount mavjud)]

  ORCH --> ETSRC[etender.uzex.uz]
  ETSRC --> ETKW[Pick keyword (kirill bo‘lsa prioritet)]
  ETKW --> ETAPI[POST https://apietender.uzex.uz/api/common/DealsList\npayload: Keyword + paging]
  ETAPI --> ETFILT[Filter: period_months]
  ETFILT --> ETEV[Evidence (unit_price = null,\nfaqat tender konteksti)]

  XEV --> OUT[Merge evidences_by_source + all_evidences]
  ETEV --> OUT
```

## Qisqa izoh (nega shunday?)

- `xarid.uzex.uz` completed-deals API’lari **product_code** bilan ishlaydi; shuning uchun avval katalogdan product_code topiladi.
- `etender.uzex.uz` DealsList endpointida **product_code** yo‘q; u keyword bo‘yicha qidiradi.
- `unit_price` faqat miqdor (`amount`) bor joyda ishonchli hisoblanadi; etender’da ko‘pincha `amount` yo‘q.

