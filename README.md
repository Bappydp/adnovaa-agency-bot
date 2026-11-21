# Agency Telegram Bot — Facebook | Google Ads Agencies

Ei bot-ta tomar agency-r Telegram promotion, lead capture ar group management — sob ek jaigay.

## Bot-ta ki ki kore (16-ta feature)

1. **Welcome + button menu** — `/start` dile Services, Pricing, Contact button ashe
2. **Service details + package/price** — 3-ta package: Starter / Growth / Premium (price ekhono example — `content.py`-te TODO lekha ache, asol price bosate hobe)
3. **FAQ auto-reply** — `/faq` + DM-e proshno likhle keyword miliye uttor dei
4. **Broadcast** — `/broadcast <message>` dile bot start kora sob user-ke message jai
5. **Force-subscribe** — group-e likhte hole age channel join korte hobe; join na korle message delete hoye jai + Join button ashe. Channel join korar porer message-tai sathe sathe jabe — **✅ I've Joined tap korte hoi na** (tap korle sudhu welcome message-ta ashe)
6. **Admin stats** — `/stats`: total user, ajker/ei week-er notun user, kon button-e koto click, top command, lead, VIP count
7. **Payment info** — payment method dekhai (wallet address ekhono placeholder — `PASTE_YOUR_WALLET_HERE`, asol address bosate hobe)
8. **Coupon system** — `/addcoupon CODE PERCENT EXPIRY`, user `/redeem CODE` diye use kore (jon proti 1 bar, expiry check hoi)
9. **Giveaway / contest** — `/giveaway Title | din` diye toiri, referral link-e +1 entry, `/draw` diye winner tola
10. **Keyword auto-reply (group)** — group-e keu "price", "service", "audit" likhle bot uttor dei; `/addkeyword` / `/delkeyword` diye notun word add/remove kora jai
11. **VIP membership** — `/vip <user_id>` dile oi user VIP menu + special offer pai
12. **Lead follow-up** — Pricing/Services/Contact dekhle user "lead" hoi; 3 din chup thakle bot nijei follow-up message pathai (sorbochcho 2 bar, tarpor ar na)
13. **Group anti-spam** — obvious spam (crypto scam, casino, adult spam, 3+ link, notun member-er link+mention) auto delete hoi; 3-ta strike 24 ghontai = ban. `/spamstats`, `/addspamword`, `/delspamword`, `/spamwords`
14. **/report** — member group-e kono message-e reply diye `/report` dile admin-der kache jai, sathe Delete / Ban / Dismiss button
15. **Admin alert** — 1 ghontai 5+ jon leave korle alert; bot-ke group/channel theke sorale ba admin power kere nile sathe sathe alert. `/alerts` diye obostha dekha jai
16. **Welcome editor** — `/setwelcome` diye group-er welcome message tumi nije set korte paro (text ba chobi + caption); `/welcome` diye preview, `/resetwelcome` diye default-e fera jai

> ⚠️ **Ekta sotti kotha:** kono bot-i kauke channel report kora thekate pare na — report kora Telegram-er nijer system, ar report-er por ki hobe seta sudhu Telegram decide kore. Ei protection feature-gulo spam komiye report howar karon komai, kintu channel-ke "report-proof" banate pare na. Channel clean rakhlei sobcheye boro protection.

---

## Shuru korar age ja lagbe

| Jinish | Kotha theke pabe |
|---|---|
| **BOT_TOKEN** | @BotFather theke (niche Step 1) |
| **Tomar Telegram user ID** | `6824922316` — **age thekei admin hisebe bosano ache**, alada kore bosate hobe na (niche Step 3) |
| **Channel username** | `@facebookads_adnovaa` — https://t.me/facebookads_adnovaa (config-e default hisebe bosano ache) |

---

## Step 1 — BotFather theke bot banano (2 minute)

1. Telegram-e **@BotFather** kholo
2. `/newbot` pathao → bot-er nam dao (jemon `Agency Assistant`) → username dao (jemon `agency_helper_bot` — seshe `bot` thakte hobe)
3. BotFather je **token** dibe (lomba number:letter code) — eta copy kore rakho. Eta kauke dio na.

## Step 2 — Bot-er privacy OFF kora (khub dorkari!)

Bot jate group-er sob message dekhte pare (force-subscribe + keyword reply-r jonno):

1. @BotFather-e `/setprivacy` pathao → tomar bot select koro → **Disable** tap koro
2. Eta na korle bot group-e sudhu command dekhbe, ar force-subscribe kaj korbe na

## Step 3 — Tomar user ID (age thekei bosano)

Tomar Telegram user ID **`6824922316`** bot-er config-e admin hisebe age thekei bosano ache — Render-e `ADMIN_IDS` na bosaleo admin command kaj korbe. Jodi aro admin add korte chao, tokhon Render-e `ADMIN_IDS` env var-e comma diye ID-gulo bosao (jemon `6824922316,987654321`).

ID check korte chaile: Telegram-e **@userinfobot** kholo → `/start` pathao — je ID dibe seta miliye dekho.

## Step 4 — Render-e deploy

1. Ei folder-ta GitHub-e upload koro (repo baniye push koro)
2. [Render Dashboard](https://dashboard.render.com) → **New → Web Service** → repo select koro
3. Settings:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Plan:** Free
4. **Environment Variables**-e egulo bosao:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Step 1-er token |
| `ADMIN_IDS` | (Optional) `6824922316` age thekei default — aro admin chaile ekhane bosao |
| `CHANNEL_ID` | `@facebookads_adnovaa` (default-ei bosano ache — bodlate hole ekhane bosao) |
| `BOT_USERNAME` | `adnovaaagencybot` (default-ei bosano ache) |
| `GROUP_ID` | (Optional) group-er numeric ID — giveaway announce-er jonno |

5. **Create Web Service** tap koro. Deploy sesh hole bot cholte shuru korbe.

> ⚠️ Render free tier-e disk ephemeral — redeploy korle `bot.db` (user/coupon/giveaway data) reset hoye jabe. Pore chaile Postgres-e move kora jabe.

## Step 5 — Bot-ke group + channel-e admin kora

**Group-e (t.me/Facebook_google_adnovaa):**
1. Group → Members → Add Members → tomar bot add koro
2. Bot-ke **Admin** banau, ar ei permission-gulo ON koro:
   - ✅ **Delete Messages** (force-subscribe + anti-spam-r jonno MUST)
   - ✅ **Ban Users** (anti-spam 3-strike ban + /report-er Ban button-er jonno MUST)
   - ✅ **Send Messages**

**Channel-e (https://t.me/facebookads_adnovaa):**
1. Channel → Administrators → Add Admin → tomar bot add koro
2. Bot channel admin na hole ke channel member seta check korte parbe na — tokhon force-subscribe kaj korbe na (bot tokhon kauke block korbe na, sudhu log-e warning dibe)

## Step 6 — UptimeRobot diye bot jagiye rakha (free)

Render free service 15 minute chup thakle ghumiye jai. MC ChatBot-er motoi:

1. [UptimeRobot](https://uptimerobot.com) free account kholo
2. **Add New Monitor** → Type: HTTP(s), URL: tomar Render URL (jemon `https://agency-telegram-bot.onrender.com`)
3. Interval: **5 minutes**
4. Eta 5 minute por por ping dibe, bot ar ghumabe na

---

## Admin command-gulo

Bot-ke DM-e pathao (sudhu ADMIN_IDS-er user-ra use korte parbe):

| Command | Kaj |
|---|---|
| `/adminhelp` | Sob admin command-er list |
| `/stats` | User, click, lead, VIP stats |
| `/broadcast <message>` | Sob user-ke message pathano |
| `/addcoupon CODE PERCENT EXPIRY` | Coupon banano — jemon `/addcoupon WELCOME20 20 2026-12-31` |
| `/coupons` | Coupon list dekha |
| `/delcoupon CODE` | Coupon delete |
| `/giveaway Title \| din` | Giveaway shuru — jemon `/giveaway Free Audit \| 7` |
| `/draw` | Winner tola + announce |
| `/endgiveaway` | Winner charai giveaway bondho |
| `/giveawayinfo` | Choloman giveaway dekha |
| `/vip <user_id>` | Kauke VIP banano (ba tar message-e reply diye `/vip`) |
| `/unvip <user_id>` | VIP sorano |
| `/vipinfo` | VIP list |
| `/addkeyword word \| reply` | Group keyword add — jemon `/addkeyword website \| We build fast websites!` |
| `/delkeyword word` | Keyword delete |
| `/keywords` | Keyword list |
| `/spamstats` | Spam strike ar ban-er stats (aj / ei week) |
| `/addspamword word` | Spam word add — sudhu OBVIOUS spam word dio |
| `/delspamword word` | Spam word delete |
| `/spamwords` | Spam word list |
| `/alerts` | Group-er leave count, member count, alert obostha |
| `/setwelcome` | Group welcome message set kora (text ba chobi + caption) |
| `/welcome` | Choloman welcome message preview dekha |
| `/resetwelcome` | Custom welcome muche default-e fera |

User-ra use kore: `/start`, `/faq`, `/redeem CODE`, `/giveawayinfo`, `/report`, `/help`, `/cancel`

---

## Welcome message bodlano (/setwelcome)

Keu channel join korle tar porer group message sathe sathe jabe — kono tap korte hoi na. Ar group-e **✅ I've Joined** tap korle je welcome message-ta ashe, seta tumi nije set korte paro — bot-ke DM-e pathiye:

1. Bot-ke DM-e `/setwelcome` pathao (group-e na, bot-er sathe private chat-e)
2. Tarpor **ekta message** pathao — duto vabe:
   - **Sudhu text** — jemon `🎉 Welcome {name}! ...` — tahole text-only welcome hobe
   - **Chobi + caption** — chobi pathanor somoy caption-e lekha dio — tahole chobi soho welcome jabe (caption chara chobi cholbe na)
3. Lekhar moddhe `{name}` likhle sekhane notun member-er nam bosbe
4. Sorbochcho **1000 character** porjonto lekha jai; beshi hole bot janabe ar abar pathate bolbe
5. Majhkhane bondho korte chaile `/cancel` pathao — kichu bodlabe na

Save korar sathe sathe bot tomake **preview** dekhabe — joiner-ra thik etai dekhbe.

Prottek welcome-er niche ei 3-ta button **automatic** thakbe (text, chobi ba default — sob khetrei): **💬 Chat with Owner** (@Adnovaa_agency), **🌐 Website** (adnovaa.com), **⭐ Our Reviews** (t.me/reviewadnovaa). Button-gulo bodlano jai na — sudhu welcome-er lekha/chobi tumi set korte paro.

- `/welcome` — ekhon je welcome set ache setar preview dekha (custom na thakle default message dekhabe)
- `/resetwelcome` — custom welcome muche fela, default message-e fera

> ⚠️ Welcome setting `bot.db`-te thake — Render-e redeploy korle muche jabe (Step 4-er note dekho). Tokhon `/setwelcome` diye abar set korte hobe. Ar chobi-r file majhe majhe purono hoye gele chobi na eshe sudhu text asbe — tokhon admin-der kache alert jabe, `/setwelcome` diye notun chobi set kore nio.

---

## Price ar wallet address bodlano

Sob lekha **ekta file-e**: `content.py`

- **Package price:** `PACKAGES` list-e — ekhono example price ache, `TODO` lekha ache. Asol price bosiye redeploy koro.
- **Wallet address:** `PAYMENT_INFO`-te `PASTE_YOUR_WALLET_HERE` — asol USDT TRC20 address bosao.
- **Service list, FAQ uttor, keyword reply** — sob `content.py`-tei edit kora jai. Onno file chhute hobe na.

---

## Somossa hole

| Somossa | Karon + somadhan |
|---|---|
| Bot group-e message delete kore na | Bot group admin kina check koro, **Delete Messages** permission ON kina dekho |
| Spammer-ke ban korte pare na | Group-e bot-er **Ban Users** permission ON kina dekho; ban fail hole admin-der kache alert jai |
| Mass-leave alert ashe na | Bot group-e admin kina check koro — admin na hole Telegram join/leave update pathai na |
| Join na koreo group-e likhte pare | Bot channel-er admin kina check koro; `CHANNEL_ID` thik @username kina dekho |
| Bot group-e kono message-e respond kore na | @BotFather-e `/setprivacy` → **Disable** kora hoyeche kina dekho |
| `/stats` ba `/broadcast` kaj kore na | `ADMIN_IDS`-e tomar thik user ID boseche kina dekho (@userinfobot theke) |
| Welcome-er chobi ashe na, sudhu text ashe | Chobi-r file purono hoye geche — `/setwelcome` diye notun chobi set koro; fail hole admin-der kache alert jai |
| Bot majhe majhe reply dei na | UptimeRobot monitor chalu ache kina dekho (Step 6); Render log-e error ache kina dekho |
| Deploy fail hoi | Render log dekho — sadharonoto `requirements.txt` install ba Python version-er somossa |

Render log dekhar jonno: Render Dashboard → tomar service → **Logs** tab.
