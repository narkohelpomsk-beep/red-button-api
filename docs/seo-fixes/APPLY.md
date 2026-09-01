# Готовые правки SEO для narkohelpomsk.ru

**Статус на проде (1 сентября 2026):** правки внесены в живую тему Impulse через wp-admin (файлы `library/seo-technical.php`, `library/seo-meta.php`, футеры, шаблоны калькулятора и лендингов). Проверено снаружи: главная без `MedicalClinic` и SearchAction, есть NGO/LocalBusiness и FAQPage, `/prise/` → 301 на цены, у калькулятора есть H1, GTM один ID `GTM-PBHDQPHM`. Учётные данные WP в этот репозиторий не записывались.

Этот git-репозиторий — Python-бот (red-button-api), не исходники WordPress. Ниже — эталон для повторного применения.

Проверено по HTML сайта 1 сентября 2026. После правок в теме: очистить кэш WP Rocket.

Сниппет `functions-seo-fixes.php` дублирует часть логики темы; на проде логика стоит в `library/seo-technical.php`, второй сниппет ставить не нужно.

---

## 0. Куда вставить PHP

1. Плагин **Code Snippets** → Add new → вставить содержимое `functions-seo-fixes.php` (с `<?php` в первой строке) → Run snippet everywhere.
2. Либо файл `wp-content/mu-plugins/impulse-seo-fixes.php`.
3. Очистить WP Rocket.

Если сниппет лежит **не** рядом с JSON-файлами этого каталога, PHP всё равно выведет schema из встроенного fallback.

---

## 1. JSON-LD: MedicalClinic → NGO + LocalBusiness

**Сейчас** (footer темы / кастомный HTML): `"@type":"MedicalClinic"`. АНО по ОКВЭД 87.90 медуслуги не оказывает.

**Сделать:**

1. В теме / «Insert Headers and Footers» / виджете найти блок с `MedicalClinic` и **удалить** его (поиск по файлам: `MedicalClinic`).
2. Оставить сниппет из `functions-seo-fixes.php` — он печатает корректный граф и на всякий случай заменяет `MedicalClinic` в HTML.
3. Эталон: `schema-homepage.json`.

Ключевые поля:

- тип: `["NGO","LocalBusiness"]` — **не** `MedicalClinic`, **не** `MedicalWebPage`;
- `taxID` 5504151921, ОГРН 1175543039913, ОКВЭД 87.90;
- `postalCode` **644070** (как в 2ГИС; в schema сейчас 644000);
- `sameAs`: 2ГИС `https://2gis.ru/omsk/firm/70000001033512039` и Яндекс Карты **только** `https://yandex.ru/maps/org/impuls/199394486863/` (ID 199394486863; Справочник: https://yandex.ru/sprav/199394486863). Не подставлять женскую карту `…/impuls_plyus/56854615182/`;
- `department` — ООО «ДА-компани» как медпартнёр со ссылкой на `/licenziya/`;
- description **без** «медикаментозного лечения».

---

## 2. SearchAction vs robots.txt

`robots.txt` (Yoast) оставить как есть, поиск **не** открывать:

```
Disallow: /?s=
```

SearchAction Yoast сейчас: `https://www.narkohelpomsk.ru/?s={search_term_string}`. Сниппет снимает `potentialAction` фильтром `wpseo_schema_website`.

Проверка: в исходнике главной больше нет `"@type":"SearchAction"`, а `Disallow: /?s=` на месте.

---

## 3. Два идентификатора GTM

В HTML **не два полных контейнера**, а рассинхрон пары:

| Место | ID |
|---|---|
| `<head>` script | `GTM-PBHDQPHM` |
| `<body>` noscript iframe | `GTM-58HTBZ9X` |

**Сделать в админке:**

1. Внешний вид → редактор темы / плагин GTM / «Header and Footer»: найти оба вхождения.
2. Оставить **один** ID. Рабочий JS — `GTM-PBHDQPHM`; noscript должен быть **тем же**.
3. `GTM-58HTBZ9X` удалить, если в этом контейнере нет уникальных тегов. Сверить в tagmanager.google.com.
4. Яндекс.Метрику 96462627 не дублировать внутри GTM, если она уже идёт плагином wp-yandex-metrika.

Эталон noscript (только если оставляете PBHDQPHM):

```html
<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-PBHDQPHM"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->
```

---

## 4. Каннибализация: 301

Импорт в плагин **Redirection** (Tools → Redirection → Import) или руками. Файл: `redirects-301.csv`.

Канон ← удалить/склеить:

| Оставить | 301 с |
|---|---|
| `/czeny-na-reabilitacziyu-alko-i-narkozavisimyh/` | `/prise/` и `/prise` |
| `/reabilitaciya-narkozavisimyh/` | `/programmy-narko/` |
| `/reabilitaciya-alkozavisimyh/` | `/programmy-alkogol/` |
| `/lechenie-igromanii/` | `/lechenie-zavisimosti-ot-azartnyh-igr/` |
| `/news/` | `/news/весна-😍/` |

`/reabilitacziya/` не редиректить на алкоголь/нарко — это общая услуга.

Женская `/reabilitaciya-ot-woman-zavisimosti/`: **не** 301 без решения по бренду. Yoast → noindex + видимая ссылка на https://impulsplus55.ru/.

Nginx (если редиректы на сервере, не в WP):

```nginx
location = /prise/ { return 301 https://www.narkohelpomsk.ru/czeny-na-reabilitacziyu-alko-i-narkozavisimyh/; }
location = /prise { return 301 https://www.narkohelpomsk.ru/czeny-na-reabilitacziyu-alko-i-narkozavisimyh/; }
location = /programmy-narko/ { return 301 https://www.narkohelpomsk.ru/reabilitaciya-narkozavisimyh/; }
location = /programmy-narko { return 301 https://www.narkohelpomsk.ru/reabilitaciya-narkozavisimyh/; }
location = /programmy-alkogol/ { return 301 https://www.narkohelpomsk.ru/reabilitaciya-alkozavisimyh/; }
location = /programmy-alkogol { return 301 https://www.narkohelpomsk.ru/reabilitaciya-alkozavisimyh/; }
location = /lechenie-zavisimosti-ot-azartnyh-igr/ { return 301 https://www.narkohelpomsk.ru/lechenie-igromanii/; }
location = /lechenie-zavisimosti-ot-azartnyh-igr { return 301 https://www.narkohelpomsk.ru/lechenie-igromanii/; }
```

После 301 в Yoast у страниц-источников снять из меню и внутренней перелинковки (иначе люди ходят по цепочке).

---

## 5. H1 калькулятора и опечатка /prise/

`/rasschitat-stoimost/` — в HTML **нет** `<h1>`. Сниппет добавит его через `the_content`. Надёжнее вручную в редакторе страницы первым блоком:

```
Рассчитать стоимость реабилитации в Омске
```

(уровень H1, не H2).

`/prise/` закрывается 301 из пункта 4. Отдельный URL `/price/` не создавать, пока висит `/czeny-…/`.

---

## 6. Title / H1 / description — вставить в Yoast

SEO → страница → Yoast. H1 — в контенте темы/редактора, не в title-теге.

### Главная `/`

| Поле | Вставить |
|---|---|
| Title | `Реабилитационный центр «Импульс» в Омске — помощь при зависимости` |
| H1 | `Реабилитационный центр «Импульс» в Омске` (уже так — не менять) |
| Meta description | `АНО «ЦСП «Импульс»»: социальная реабилитация зависимости в Омске от 45 000 ₽/мес. Консультации 24/7, анонимно. Медуслуги оказывает лицензированный партнёр.` |

Сейчас title про «консультации и социальную помощь», H1 про «реабилитационный центр» — рассинхрон. Новый title начинается с той же фразы, что H1.

Yoast → Search Appearance → Graph / Schema: Organization description заменить, убрать «медикаментозное лечение». Это же поле попадает в `WebPage.description` и `WebSite.description`.

### Посадочные (после 301)

| URL | Title | H1 |
|---|---|---|
| `/reabilitaciya-narkozavisimyh/` | `Реабилитация наркозависимых в Омске — центр «Импульс»` | `Реабилитация наркозависимых в Омске` (сейчас H1 «Лечение наркомании» — не совпадает с title и спорит со страницей лицензии) |
| `/reabilitaciya-alkozavisimyh/` | `Реабилитация алкозависимых в Омске — центр «Импульс»` | `Реабилитация алкозависимых в Омске` |
| `/lechenie-igromanii/` | `Лечение игромании в Омске — реабилитация и семья, 24/7` | `Лечение игромании в Омске` |
| `/czeny-na-reabilitacziyu-alko-i-narkozavisimyh/` | `Цены на реабилитацию в Омске — детокс и программы «Импульс»` | оставить текущий H1 |
| `/informaciya-dlya-rodstvennikov/` | `Консультации для родственников зависимого — «Импульс», Омск` | `Как помочь близкому с зависимостью` |
| `/rasschitat-stoimost/` | `Рассчитать стоимость реабилитации в Омске — «Импульс»` | `Рассчитать стоимость реабилитации в Омске` |
| `/reabilitacziya/` | `Социальная реабилитация при зависимости в Омске — «Импульс»` | `Социальная реабилитация при зависимости в Омске` |

---

## 7. sameAs: 2ГИС и Яндекс Карты

**2ГИС (публичная карточка):** `https://2gis.ru/omsk/firm/70000001033512039`  
Не использовать кабинет `account.2gis.com/orgs/…12038`.

**Яндекс — две организации:**

| Бренд | Канон Карт | ID | Сайт в карточке |
|---|---|---|---|
| «Импульс» (основной) | `https://yandex.ru/maps/org/impuls/199394486863/` | 199394486863 | narkohelpomsk.ru |
| «Импульс Плюс» (женщины) | `https://yandex.ru/maps/org/impuls_plyus/56854615182/` | 56854615182 | impulsplus55.ru |

Справочник основного: `https://yandex.ru/sprav/199394486863`.

На **narkohelpomsk.ru** в `sameAs` / `hasMap` — только основная карта (без `ll`/`z`). Карту Плюса сюда не ставить.

На **impulsplus55.ru** в schema уже есть `https://yandex.ru/maps/org/impuls_plyus/56854615182/` (WP-админки у плюса нет: `/wp-admin/` и `/wp-login.php` отдают 404). Там же ошибочно `sameAs` на 2ГИС основного `…12039` — править, когда появится CMS-доступ.

**В Яндекс Бизнесе (не в git):** третью карточку не создавать. Если разные юрлица — не склеивать. У Плюса: название «Импульс Плюс», сайт только impulsplus55.ru, телефон только +7 962 053-18-63 (убрать общие 909/965). Цель — чтобы запрос «реабилитационный центр импульс омск» вёл на 199394486863.

---

## 8. FAQPage

Вопросы с главной уже в `schema-faqpage.json`. Сниппет выводит FAQPage только на `is_front_page()`.

Не дублировать второй FAQPage плагином FAQ, если сниппет включён.

---

## 9. Breadcrumb главной

Сейчас BreadcrumbList из одного пункта: «Главная страница». Сниппет отключает `wpseo_schema_breadcrumb` на главной (`return false`).

На внутренних страницах крошки оставить.

---

## 10. og:image 1200×630

Файл: `assets/og-image-1200x630.jpg` (1200×630, JPEG, сделан из текущего `intro_page_1.png` с полями).

1. Медиафайлы → загрузить.
2. Скопировать в постоянный путь, например `/wp-content/uploads/og-image-1200x630.jpg` (сниппет ждёт именно его).
3. Yoast → страница главной → Social → Image, либо Search Appearance → General → Knowledge Graph / Social.

Проверка: `og:image:width` = 1200, `og:image:height` = 630.

---

## 11. Новости с кириллицей и эмодзи в slug

58 из 78 URL в `news-sitemap.xml` — кириллица; один со смайлом (`/news/весна-😍/`). Список: `news-cyrillic-slugs.txt`.

Сниппет ставит `noindex, follow` и выкидывает их из sitemap Yoast.

Вручную для новых новостей: латинский slug **до** публикации (экран редактора → ЧПУ). Старые массово не переименовывать без 301.

Эмодзи-URL — 301 на `/news/` (уже в CSV).

---

## 12. Проверка после выкладки

```bash
curl -sL https://www.narkohelpomsk.ru/ | grep -oE 'GTM-[A-Z0-9]+' | sort -u
# ожидается один ID

curl -sL https://www.narkohelpomsk.ru/ | grep -c MedicalClinic
# 0

curl -sL https://www.narkohelpomsk.ru/ | grep -c SearchAction
# 0

curl -sL https://www.narkohelpomsk.ru/ | grep -c FAQPage
# ≥ 1

curl -sI https://www.narkohelpomsk.ru/prise/ | grep -i location
# Location: .../czeny-na-reabilitacziyu-alko-i-narkozavisimyh/

curl -sL https://www.narkohelpomsk.ru/rasschitat-stoimost/ | grep -o '<h1[^>]*>.*</h1>'
```

Google Business Profile из репозитория не создать. Публичный URL по cid `16892342034457875612` не найден (Карты пустые, не Омск) — нужна ссылка `google.com/maps/place/...`. Карточки Яндекс: основной `199394486863`, Плюс `56854615182`.
