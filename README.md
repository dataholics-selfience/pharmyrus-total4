# Pharmyrus API - Deploy Railway

## 🚀 DEPLOY

```bash
railway up
```

## 📁 ARQUIVOS

- `main.py` - API FastAPI
- `serpapi_pool.py` - Pool de 9 keys SerpAPI
- `requirements.txt` - Dependências
- `Procfile` - Comando de start

## ✅ ENDPOINTS

```
GET /health
GET /api/v1/search?molecule_name=Darolutamide
GET /api/v1/serpapi/status
GET /api/v1/serpapi/key
```

## 🔑 POOL SERPAPI

9 keys configuradas = 2.250 queries/mês
- 7 disponíveis (1.750 queries)
- Rotação automática
- Reset mensal

## 🧪 TESTAR

```bash
curl https://seu-app.railway.app/health
curl https://seu-app.railway.app/api/v1/serpapi/status
curl "https://seu-app.railway.app/api/v1/search?molecule_name=Darolutamide"
```

## ⚙️ CONFIGURAÇÃO

Nenhuma variável necessária! Railway define PORT automaticamente.

