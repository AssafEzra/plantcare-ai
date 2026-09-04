# PlantCare AI — UI_DESIGN_TOKENS_AND_WIREFRAMES.md

## MVP direction
Hebrew-only, RTL, Streamlit, desktop-first/responsive, sidebar navigation, calm premium natural visual language. The approved mockup remains the source of truth for exact visual details.

## Design tokens

### Color
```css
:root {
  --pc-bg:#F7F5EF;
  --pc-surface:#FFFFFF;
  --pc-surface-soft:#F0EFE8;
  --pc-text:#243027;
  --pc-text-muted:#6B756D;
  --pc-border:#E1E3DC;
  --pc-primary:#2F6B4F;
  --pc-primary-dark:#24533D;
  --pc-primary-soft:#E5F0E9;
  --pc-success:#3F7D55;
  --pc-success-soft:#E8F3EB;
  --pc-warning:#A96F24;
  --pc-warning-soft:#F8EEDC;
  --pc-danger:#A94A43;
  --pc-danger-soft:#F7E8E6;
  --pc-neutral:#66706A;
  --pc-neutral-soft:#ECEEEA;
}
```

### Typography
```css
--pc-font-family:"Noto Sans Hebrew","Assistant",Arial,sans-serif;
```
Display 32/700; H1 28/700; H2 22/700; H3 18/700; Body 16/400; Small 14/400; Caption 12/500.

### Spacing
`4, 8, 12, 16, 20, 24, 32, 40, 48, 64px`

### Radius
`8, 12, 16, 24, 999px`; standard card radius 16px.

### Shadows
`0 2px 12px rgba(36,48,39,.06)` and `0 8px 28px rgba(36,48,39,.10)`.

### Layout
Max width 1280px; sidebar 240–280px; page padding 24–40px; card gap 16–24px.

## Status
Always text + icon:
```text
✓ בריא
⚠ דורש תשומת לב
! מצב קריטי
? לא ידוע
```
Color alone must never communicate status.

## Sidebar
```text
┌──────────────────────────────┐
│          PlantCare AI        │
│                              │
│  🏠  בית                     │
│  🌿  הצמחים שלי              │
│                              │
│  ──────────────────────────  │
│  ⚙  הגדרות                   │
│  Admin Panel — admins only   │
│                              │
│  משתמש                       │
│  יציאה                       │
└──────────────────────────────┘
```

## Home Dashboard
```text
┌──────────────────────────────────────────────────────────────┐
│ שלום 👋                              [התראות] [פרופיל]        │
│ היום בגינה שלך                                                │
│ ┌────────────────────────┐ ┌──────────────────────────────┐ │
│ │ הטיפול של היום         │ │ דורש תשומת לב                │ │
│ │ 🌿 מונסטרה             │ │ ⚠ סנסיווריה                  │ │
│ │ השקיה · 08:00          │ │ בדיקת בריאות                 │ │
│ │ [בוצע] [דלג]           │ │ [בדיקת בריאות]               │ │
│ └────────────────────────┘ └──────────────────────────────┘ │
│ הצמחים שלי                              [הוסף צמח +]         │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐                     │
│ │  תמונה   │ │  תמונה   │ │  תמונה   │                     │
│ │ מונסטרה  │ │ פיקוס    │ │ סנסיווריה│                     │
│ │ ✓ בריא   │ │ ✓ בריא   │ │ ⚠ תשומת לב│                   │
│ └──────────┘ └──────────┘ └──────────┘                     │
└──────────────────────────────────────────────────────────────┘
```
Goal: user understands today's actions within seconds.

## My Plants
```text
┌──────────────────────────────────────────────────────────────┐
│ הצמחים שלי                              [ + הוסף צמח ]        │
│ [ חיפוש צמח... ]            [מיון] [סינון לפי בריאות]        │
│ ┌────────────┐ ┌────────────┐ ┌────────────┐                │
│ │   IMAGE    │ │   IMAGE    │ │   IMAGE    │                │
│ │ המונסטרה   │ │ הפיקוס     │ │ הסנסיווריה │                │
│ │ ✓ בריא     │ │ ✓ בריא     │ │ ⚠ תשומת לב │                │
│ │ השקיה מחר  │ │ דישון בשישי│ │ בדיקת בריאות│               │
│ └────────────┘ └────────────┘ └────────────┘                │
└──────────────────────────────────────────────────────────────┘
```
Each card opens Plant Dashboard. Empty state offers first plant.

## Add Plant
### Upload
```text
┌────────────────────────────────────────────────────────────┐
│ הוסף צמח · שלב 1 מתוך 3                                    │
│ צלם או העלה תמונות של הצמח                                 │
│        ┌──────────────────────────────┐                    │
│        │          + הוסף תמונה         │                    │
│        └──────────────────────────────┘                    │
│ [thumbnail] [thumbnail] [thumbnail]                         │
│                              [המשך לזיהוי →]                │
└────────────────────────────────────────────────────────────┘
```

### Processing
```text
✓ התמונות התקבלו
✓ ההקשר נטען
● מנתחים את התמונות
○ מכינים את התוצאה
```

### Confirmation
```text
┌────────────────────────────────────────────────────────────┐
│ הזיהוי הושלם                                                │
│ ┌──────────────────┐  מונסטרה דליסיוסה                     │
│ │      IMAGE       │  Monstera deliciosa                    │
│ └──────────────────┘  רמת ביטחון: גבוהה                    │
│ אפשרויות נוספות: Monstera adansonii / ...                  │
│ מידע נוסף: [ויקיפדיה ↗]                                   │
│ [✓ זה הצמח שלי]                  [נסה שוב]                  │
└────────────────────────────────────────────────────────────┘
```
No manual Species selection. Wikipedia appears only when a real relevant page exists.

## Knowledge Pending
```text
┌────────────────────────────────────────────────────────────┐
│ כמעט סיימנו                                                 │
│ זיהינו את הצמח שלך ומכינים עבורו מידע מקצועי.               │
│ ✓ הזיהוי אושר                                               │
│ ✓ הצמח נוסף                                                 │
│ ● הכנת מידע מקצועי                                         │
│ ○ אישור מידע                                                │
│ אפשר להמשיך להשתמש באפליקציה.                               │
└────────────────────────────────────────────────────────────┘
```

## Plant Dashboard
```text
┌──────────────────────────────────────────────────────────────┐
│ ← הצמחים שלי                                                │
│ ┌──────────────────┐  המונסטרה בסלון                       │
│ │    MAIN IMAGE    │  Monstera deliciosa                    │
│ └──────────────────┘  ✓ בריא                                │
│ [בדיקת בריאות] [עדכון סביבה] [עריכת שם]                    │
│ ┌────────────────────────┐ ┌──────────────────────────────┐ │
│ │ הטיפול הקרוב           │ │ תוכנית הטיפול                │ │
│ │ השקיה מחר · 08:00      │ │ השקיה כל 7 ימים              │ │
│ │ [בוצע] [דלג]           │ │ דישון כל 30 ימים             │ │
│ └────────────────────────┘ └──────────────────────────────┘ │
│ בריאות · בדיקה אחרונה · מגמה · היסטוריה · מידע מקצועי       │
└──────────────────────────────────────────────────────────────┘
```

## Care Plan Proposal
```text
┌────────────────────────────────────────────────────────────┐
│ תוכנית טיפול מוצעת                                         │
│ 💧 השקיה · כל 7 ימים                                       │
│ ☀ אור · אור בהיר, ללא שמש ישירה                           │
│ 🌱 דישון · פעם בחודש                                      │
│ ─────────────────────────────────────────────────────────  │
│ העדפות שלך · שעה מועדפת [08:00]                            │
│ [אישור תוכנית]                 [דחייה]                     │
└────────────────────────────────────────────────────────────┘
```
Professional recommendation and operational preference are separate. Operational changes create a new version with Change Summary.

## Health Check
```text
┌────────────────────────────────────────────────────────────┐
│ בדיקת בריאות                                               │
│ העלה 1–4 תמונות של הצמח                                    │
│ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐               │
│ │+ תמונה │ │ תמונה  │ │ תמונה  │ │ תמונה  │               │
│ └────────┘ └────────┘ └────────┘ └────────┘               │
│ הערה קצרה (אופציונלי):                                    │
│ [ העלים החדשים מצהיבים... ]                               │
│ [התחל בדיקת בריאות]                                       │
└────────────────────────────────────────────────────────────┘
```

## Health Result
```text
┌────────────────────────────────────────────────────────────┐
│ תוצאות בדיקת הבריאות                                       │
│ ⚠ דורש תשומת לב · רמת ביטחון: בינונית                     │
│ מה ראינו? • עלים מצהיבים • שינוי בעלים התחתונים           │
│ אפשרויות אפשריות • השקיית יתר • חוסר באור                 │
│ מה אפשר לעשות? • לבדוק לחות • לוודא ניקוז                 │
│ 💡 שינוי אפשרי בתוכנית [הצג הצעת שינוי]                    │
└────────────────────────────────────────────────────────────┘
```
Never present a definitive diagnosis.

## Settings
```text
┌────────────────────────────────────────────────────────────┐
│ הגדרות                                                      │
│ שם [................]                                       │
│ אזור זמן [Asia/Jerusalem ▼]                               │
│ [✓] תזכורות במייל · שעה [08:00]                            │
│ [✓] סיכום יומי                                              │
│ [שמור]                                                      │
└────────────────────────────────────────────────────────────┘
```

## Admin Panel
Admin only:
```text
┌──────────────────────────────────────────────────────────────┐
│ Admin Panel                                                  │
│ [Knowledge Drafts] [Published Knowledge] [Sources]           │
│ [Reports] [AI Monitoring]                                    │
│ Monstera deliciosa · ממתין לבדיקה · 8 מקורות               │
│ [צפה] [אשר] [דחה]                                           │
│ Agent | Model | Status | Duration | Cost                     │
└──────────────────────────────────────────────────────────────┘
```

## Responsive
Desktop: visible sidebar, 3–4 cards/row. Tablet: collapsible sidebar, 2 cards/row. Mobile: compact navigation, single-column cards, prominent plant image and visible primary CTA.

## Streamlit structure
```text
ui/components/
  app_shell.py
  sidebar.py
  page_header.py
  status_badge.py
  plant_card.py
  care_task_card.py
  health_card.py
  ai_processing_state.py
  image_uploader.py
  proposal_card.py
  empty_state.py
  confirmation_dialog.py

pages/
  home.py
  my_plants.py
  add_plant.py
  plant_dashboard.py
  settings.py
  admin.py
```
Business logic stays outside UI components.

## Accessibility
Keyboard accessible controls, visible focus, readable sizes, status text + icon, meaningful alt text, clear errors, no critical icon-only actions, explicit RTL.
