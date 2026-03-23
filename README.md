# Астрологическое приложение Fullstack

Полноценное веб-приложение для астрологии с расчётом натальных карт, синастрий и AI-интерпретациями.

## Возможности

- ✨ Расчёт натальной карты (положение планет, знаки Зодиака, асцендент)
- 🔮 Вычисление аспектов между планетами
- 🤝 Синастрия (совместимость двух человек)
- 📊 Визуализация зодиакального круга
- 🎯 AI-интерпретация натальной карты
- 🌙 Расчёт солярных возвращений
- ⭐ Текущие транзиты планет

## Технологический стек

| Компонент | Технология |
|-----------|------------|
| Frontend | React + Vite |
| Backend | FastAPI + SQLAlchemy |
| База данных | SQLite |
| Астрология | ephem (Swiss Ephemeris) |
| Стили | CSS (тёмная космическая тема) |

## Запуск

### Backend

```bash
cd backend
pip install -r requirements.txt
source venv/bin/activate
python -m uvicorn app.main:app --reload
uvicorn app.main:app --reload --port 8010
```

API будет доступно на http://localhost:8000
Документация: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Приложение будет доступно на http://localhost:5173

## API Endpoints

- `POST /api/users` - Создание пользователя
- `POST /api/charts` - Расчёт натальной карты
- `GET /api/charts/{id}` - Получение карты
- `POST /api/charts/{id}/interpret` - AI-интерпретация
- `GET /api/charts/{id}/solar-return` - Солярное возвращение
- `GET /api/charts/{id}/transits` - Текущие транзиты
- `POST /api/synastry` - Расчёт синастрии

## Структура проекта

```
/workspace/project/
├── backend/
│   ├── app/
│   │   ├── api/          # API эндпоинты
│   │   ├── core/         # Конфигурация
│   │   ├── db/           # База данных
│   │   ├── models/       # SQLAlchemy модели
│   │   ├── schemas/      # Pydantic схемы
│   │   └── utils/        # Астрологические расчёты
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/   # UI компоненты
│   │   ├── pages/       # Страницы
│   │   ├── services/    # API клиент
│   │   └── styles/      # CSS стили
│   └── package.json
└── README.md
```

## Переменные окружения

### Backend (.env)

```env
PROJECT_NAME="Astrology API"
DATABASE_URL=sqlite+aiosqlite:///./astrology.db
OPENAI_API_KEY=your-openai-api-key-here
```

### Frontend (.env)

```env
VITE_API_URL=http://localhost:8000
```

## Лицензия

MIT
