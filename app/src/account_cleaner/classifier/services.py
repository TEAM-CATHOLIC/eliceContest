"""Display identities from explicit mail text; unresolved IDs never route to websites."""

import hashlib
import re


def unresolved_domain(provider, name):
    # Distinct inventory keys, deliberately not a real website or a playbook target.
    key = hashlib.sha256(f"{provider}:{name}".encode()).hexdigest()[:20]
    return f"unresolved-{key}.invalid"


def resolve_service(mail):
    domain = mail.sender_domain.lower()
    subject = mail.subject.strip()
    text = subject + " " + mail.body_text[:700]
    if domain == "google.com":
        match = re.fullmatch(r"Google 계정 데이터 일부를 (.+?)에 공유하셨습니다", subject)
        if match:
            app = match.group(1)
            return LINKED_SERVICES.get(app, (app, unresolved_domain("google", app)))
    if domain == "kakaocorp.com":
        if "카카오디벨로퍼스" in text:
            return "카카오디벨로퍼스", "developers.kakao.com"
        return "카카오계정", "accounts.kakao.com"
    if domain == "cafe24shop.com":
        match = re.match(r"\[([^\]]{1,100})\]", subject)
        if match and match.group(1) not in ("광고", "AD", "ad"):
            brand = match.group(1)
            return CAFE24_STORES.get(brand, (brand, unresolved_domain("cafe24", brand)))
        return None
    if domain in PROCESSORS:
        if "제로투히어로" in text:
            return "제로투히어로", "zerotohero.co.kr"
        return None
    if domain in PERSONAL_MAIL:
        # Mail from a person's mailbox is not mail from that mailbox provider's service.
        return None
    for root, service in SERVICE_FAMILIES.items():
        # One service often sends from several subdomains; keep them as one candidate.
        if domain == root or domain.endswith("." + root):
            return service
    if domain in SERVICES:
        return SERVICES[domain]
    root = registrable_domain(domain)
    return SERVICES.get(root, (root, root))


_SECOND_LEVEL = {"co", "or", "go", "ac", "re", "ne", "pe", "com", "net", "org", "gov", "edu"}


def registrable_domain(domain):
    """info.mexc.com -> mexc.com, mail.example.co.kr -> example.co.kr (no public suffix list)."""
    parts = domain.split(".")
    if ":" in domain or parts[-1].isdigit():  # IP addresses (e.g. the local demo) stay as-is
        return domain
    keep = 3 if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL else 2
    return ".".join(parts[-keep:])


SERVICE_FAMILIES = {
    "dropbox.com": ("Dropbox", "dropbox.com"),
    "github.com": ("GitHub", "github.com"),
    "linkedin.com": ("LinkedIn", "linkedin.com"),
}


PERSONAL_MAIL = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "naver.com",
        "hanmail.net",
        "daum.net",
        "nate.com",
        "kakao.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "yahoo.com",
        "yahoo.co.kr",
        "icloud.com",
        "me.com",
    }
)


CAFE24_STORES = {
    "르아르": ("르아르", "leire.co.kr"),
    "비욘드그루밍": ("비욘드그루밍", "bgroom.co.kr"),
    "언더70": ("언더70", "under70.kr"),
    "디자인스킨 케이스 몰": ("디자인스킨 케이스 몰", "designskin.com"),
    "다슈코리아(주)": ("다슈코리아(주)", "hairwax.co.kr"),
}


SERVICES = {
    "3o3.co.kr": ("삼쩜삼", "3o3.co.kr"),
    "account.ubisoft.com": ("Ubisoft", "ubisoft.com"),
    "actoz.com": ("파이널판타지14", "ff14.co.kr"),
    "battle.net": ("Battle.net", "battle.net"),
    "bgf.co.kr": ("CU 멤버십", "bgf.co.kr"),
    "bithumbcorp.com": ("빗썸", "bithumb.com"),
    "bkr.co.kr": ("버거킹", "bkr.co.kr"),
    "communication.microsoft.com": ("Microsoft", "microsoft.com"),
    "cultureland.co.kr": ("컬쳐랜드", "cultureland.co.kr"),
    "customer.kmong.com": ("크몽", "kmong.com"),
    "dacon.io": ("데이콘", "dacon.io"),
    "discord.com": ("Discord", "discord.com"),
    "dunamu.com": ("증권플러스 비상장", "dunamu.com"),
    "e.coupang.com": ("쿠팡", "coupang.com"),
    "em.riotgames.com": ("라이엇게임즈", "riotgames.com"),
    "email.claude.com": ("Claude", "claude.ai"),
    "everytime.kr": ("에브리타임", "everytime.kr"),
    "facebookmail.com": ("Meta", "facebook.com"),
    "glyde.co.kr": ("글라이드", "glyde.co.kr"),
    "google.com": ("Google", "google.com"),
    "hanafn.com": ("하나은행", "hanafn.com"),
    "hanamembership.com": ("하나머니", "hanamembership.com"),
    "hancom.com": ("한글과컴퓨터", "hancom.com"),
    "hrc.co.kr": ("한국리서치", "hrc.co.kr"),
    "inflearn.com": ("인프런", "inflearn.com"),
    "iparking.co.kr": ("아이파킹", "iparking.co.kr"),
    "jinhakapply.com": ("진학어플라이", "jinhakapply.com"),
    "joongang.co.kr": ("중앙일보", "joongang.co.kr"),
    "k1.email.samsung.com": ("삼성닷컴", "samsung.com"),
    "kakaoent.com": ("멜론", "melon.com"),
    "kakaogames.com": ("Daum 게임", "game.daum.net"),
    "kakaopage.com": ("카카오페이지", "kakaopage.com"),
    "kbanknow.com": ("케이뱅크", "kbanknow.com"),
    "kiwoom.com": ("키움증권", "kiwoom.com"),
    "kr.email.samsung.com": ("삼성닷컴", "samsung.com"),
    "kr.temuemail.com": ("Temu", "temu.com"),
    "kyobobook.co.kr": ("교보문고", "kyobobook.co.kr"),
    "laftel.net": ("라프텔", "laftel.net"),
    "locallive.com": ("로컬라이브", "locallive.com"),
    "lpoint.com": ("L.POINT", "lpoint.com"),
    "mail.adobe.com": ("Adobe", "adobe.com"),
    "mail.kakaobank.com": ("카카오뱅크", "kakaobank.com"),
    "mail.notion.so": ("Notion", "notion.so"),
    "mail.pmang.com": ("피망", "pmang.com"),
    "mail.tossinvest.com": ("토스증권", "tossinvest.com"),
    "mailer.netflix.com": ("Netflix", "netflix.com"),
    "mailinfo.saramin.co.kr": ("사람인", "saramin.co.kr"),
    "mgdirectmail.binance.com": ("Binance", "binance.com"),
    "musinsa.com": ("무신사", "musinsa.com"),
    "navercorp.com": ("네이버", "naver.com"),
    "newsletter.trip.com": ("Trip.com", "trip.com"),
    "newsletter.wantedlab.com": ("원티드", "wanted.co.kr"),
    "nmp-corp.com": ("게토", "geto.co.kr"),
    "notification.mexc.link": ("MEXC", "mexc.com"),
    "notificationemails.microsoft.com": ("Microsoft", "microsoft.com"),
    "order.temu.com": ("Temu", "temu.com"),
    "origin.or.kr": ("FTA 원산지아카데미", "origin.or.kr"),
    "polarisoffice.com": ("폴라리스오피스", "polarisoffice.com"),
    "samsung-mail.com": ("삼성계정", "account.samsung.com"),
    "samsung.com": ("삼성자산운용 펀드솔루션", "samsung.com"),
    "seoul.go.kr": ("서울시 누리집", "seoul.go.kr"),
    "shilladfs.com": ("신라면세점", "shilladfs.com"),
    "shinsegae.com": ("신세계 채용", "shinsegae.com"),
    "signup.aws": ("AWS", "aws.amazon.com"),
    "smartthings.com": ("SmartThings", "smartthings.com"),
    "sooplive.co.kr": ("SOOP", "sooplive.co.kr"),
    "spotv.net": ("SPOTV NOW", "spotv.net"),
    "steampowered.com": ("Steam", "steampowered.com"),
    "stockplus.com": ("증권플러스", "stockplus.com"),
    "sysmail.lglifecare.com": ("LG 라이프케어", "lglifecare.com"),
    "tmon.co.kr": ("티몬", "tmon.co.kr"),
    "upbit.com": ("업비트", "upbit.com"),
    "updates.notion.so": ("Notion", "notion.so"),
    "wadiz.kr": ("와디즈", "wadiz.kr"),
    "watcha.net": ("왓챠", "watcha.com"),
    "wconcept.co.kr": ("W컨셉", "wconcept.co.kr"),
    "wooribank.com": ("우리은행", "wooribank.com"),
    "wooricard.com": ("우리WON멤버스", "wooricard.com"),
    "woowahan.com": ("배달의민족", "baemin.com"),
    "ybtour.co.kr": ("노랑풍선", "ybtour.co.kr"),
    "yogiyo.co.kr": ("요기요", "yogiyo.co.kr"),
    "zerotohero.co.kr": ("제로투히어로", "zerotohero.co.kr"),
    "zoom.us": ("Zoom", "zoom.us"),
}


LINKED_SERVICES = {
    "Adobe": ("Adobe", "adobe.com"),
    "Claude": ("Claude", "claude.ai"),
    "GrabTaxi": ("Grab", "grab.com"),
    "JOBKOREA": ("잡코리아", "jobkorea.co.kr"),
    "MEXC": ("MEXC", "mexc.com"),
    "OpenAI": ("OpenAI", "openai.com"),
    "Zoom": ("Zoom", "zoom.us"),
    "certpia.com": ("써트피아", "certpia.com"),
    "dacon-new": ("데이콘", "dacon.io"),
    "docker.com": ("Docker", "docker.com"),
    "genspark.ai": ("Genspark", "genspark.ai"),
    "roboflow.com": ("Roboflow", "roboflow.com"),
}


PROCESSORS = {
    "bill-mail.tosspayments.com",
    "inicis.com",
    "easypay.co.kr",
    "tosspayments.com",
    "kcp.co.kr",
}
