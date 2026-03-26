# Настройка Supabase для аутентификации

## 📋 Что такое Supabase?

Supabase - это open-source альтернатива Firebase, которая предоставляет:
- **Supabase Auth** - полная система аутентификации
- **Автоматическое подтверждение email**
- **Google OAuth из коробки**
- **Безопасное хранение паролей**
- **JWT токены с настройками**

## 🚀 Быстрый старт

### 1. Получите ключи Supabase

1. Зайдите в [Supabase Dashboard](https://app.supabase.com/)
2. Создайте новый проект или используйте существующий
3. Перейдите в **Project Settings > API**
4. Скопируйте:
   - **URL** (например: `https://wsqknvxhdcernpgdeyte.supabase.co`)
   - **anon/public key** (начинается с `eyJ...`)
   - **JWT Secret** (в **Project Settings > API > JWT Settings**)

### 2. Настройте переменные окружения

Создайте файл `.env` в корне проекта:

```bash
# Supabase Configuration
SUPABASE_URL=https://wsqknvxhdcernpgdeyte.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_JWT_SECRET=your-supabase-jwt-secret-here

# Database (для обратной совместимости)
DATABASE_URL=sqlite+aiosqlite:///./astrology.db
```

### 3. Настройте Supabase Auth

В Supabase Dashboard:

1. **Authentication > Providers**
   - Включите **Email/Password**
   - Включите **Google OAuth** (нужно настроить OAuth клиент в Google Cloud)

2. **Authentication > Email Templates**
   - Настройте шаблоны email для подтверждения и сброса пароля
   - URL подтверждения: `http://localhost:12001/verify-email`
   - URL сброса пароля: `http://localhost:12001/reset-password`

3. **Authentication > URL Configuration**
   - Site URL: `http://localhost:12001`
   - Redirect URLs: `http://localhost:12001/auth/callback`

### 4. Настройте Google OAuth (опционально)

1. Создайте проект в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте OAuth 2.0 Client ID
3. Добавьте authorized redirect URI:
   ```
   https://wsqknvxhdcernpgdeyte.supabase.co/auth/v1/callback
   ```
4. Скопируйте Client ID и Client Secret в Supabase **Authentication > Providers > Google**

## 🔧 Эндпоинты Supabase

### Регистрация
```
POST /api/supabase/register
{
  "email": "user@example.com",
  "password": "Password123",
  "name": "Иван Иванов"
}
```

**Ответ:**
```json
{
  "message": "Регистрация успешна! Проверьте ваш email для подтверждения.",
  "user_id": "uuid-here",
  "email_sent": true
}
```

### Вход
```
POST /api/supabase/login
{
  "email": "user@example.com",
  "password": "Password123"
}
```

**Ответ:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "expires_at": 1234567890,
  "user": {
    "id": "uuid-here",
    "email": "user@example.com",
    "name": "Иван Иванов",
    "email_confirmed_at": "2024-01-01T12:00:00Z"
  }
}
```

### Получение информации о пользователе
```
GET /api/supabase/me
Authorization: Bearer <access_token>
```

### Выход
```
POST /api/supabase/logout
Authorization: Bearer <access_token>
```

### Повторная отправка email для подтверждения
```
POST /api/supabase/resend-confirmation?email=user@example.com
```

### Сброс пароля
```
POST /api/supabase/reset-password?email=user@example.com
```

### Вход через Google
```
GET /api/supabase/google/login?redirect_to=http://localhost:12001/auth/callback
```

### Dashboard (требует аутентификации)
```
GET /api/supabase/dashboard
Authorization: Bearer <access_token>
```

## 🔐 Безопасность

### Хранение токенов на фронтенде
```javascript
// Сохраняем токены
localStorage.setItem('supabase_access_token', access_token);
localStorage.setItem('supabase_refresh_token', refresh_token);

// Используем в запросах
const response = await fetch('/api/supabase/me', {
  headers: {
    'Authorization': `Bearer ${localStorage.getItem('supabase_access_token')}`
  }
});
```

### Обновление токенов
Токены истекают через 1 час. Используйте refresh token для получения нового access token:
```
POST /api/supabase/refresh-token
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

## 🚨 Ошибки

### Email не подтвержден
```json
{
  "detail": "Email не подтвержден. Проверьте вашу почту."
}
```

### Неверные учетные данные
```json
{
  "detail": "Неверный email или пароль"
}
```

### Пользователь уже существует
```json
{
  "detail": "Пользователь с таким email уже существует"
}
```

## 📊 Миграция с локальной аутентификации

### Старые эндпоинты (для обратной совместимости)
- `/api/auth/register` → `/api/supabase/register`
- `/api/auth/login` → `/api/supabase/login`
- `/api/auth/me` → `/api/supabase/me`
- `/api/auth/logout` → `/api/supabase/logout`
- `/api/dashboard` → `/api/supabase/dashboard`

### Новые возможности Supabase
- ✅ Автоматическое подтверждение email
- ✅ Google OAuth из коробки
- ✅ Сброс пароля
- ✅ Управление сессиями
- ✅ Безопасное хранение паролей

## 🧪 Тестирование

1. **Регистрация:** Проверьте что email приходит
2. **Подтверждение:** Нажмите на ссылку в email
3. **Вход:** Войдите с подтвержденным email
4. **Dashboard:** Проверьте доступ к защищенным эндпоинтам
5. **Выход:** Проверьте что токены очищаются

## 🔗 Полезные ссылки

- [Supabase Documentation](https://supabase.com/docs)
- [Supabase Auth](https://supabase.com/docs/guides/auth)
- [Google OAuth Setup](https://supabase.com/docs/guides/auth/social-login/auth-google)
- [Email Templates](https://supabase.com/docs/guides/auth/auth-email-templates)