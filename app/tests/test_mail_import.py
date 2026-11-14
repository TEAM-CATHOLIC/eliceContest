"""메일 가져오기 테스트. 샘플 메일은 모두 테스트 안에서 직접 만든 합성 메일이다 (NF-01)."""

import base64
import io
import quopri
import zipfile
from datetime import UTC, datetime, timedelta, timezone

import pytest

from account_cleaner.mail import (
    FileMailSource,
    ImportCancelled,
    MailParseError,
    UnsupportedFileError,
    decode_bytes,
    import_mails,
    iter_mbox,
    parse_mail,
)

KST = timezone(timedelta(hours=9))


def raw_mail(
    *,
    sender="샘플쇼핑 <no-reply@Shop.Example.com>",
    subject="가입을 환영합니다",
    date="Sat, 14 Nov 2026 10:00:00 +0900",
    message_id="<1@shop.example.com>",
    body=b"hello",
    headers=(),
    content_type="text/plain; charset=utf-8",
    cte="8bit",
) -> bytes:
    lines = []
    if sender is not None:
        lines.append(f"From: {sender}")
    if date is not None:
        lines.append(f"Date: {date}")
    if message_id is not None:
        lines.append(f"Message-ID: {message_id}")
    lines += [f"Subject: {subject}", *headers, "MIME-Version: 1.0"]
    lines += [f"Content-Type: {content_type}", f"Content-Transfer-Encoding: {cte}"]
    return "\r\n".join(lines).encode("utf-8") + b"\r\n\r\n" + body


def b64_word(text: str, charset: str) -> str:
    return f"=?{charset}?B?{base64.b64encode(text.encode(charset)).decode()}?="


def mbox_of(*mails: bytes) -> bytes:
    out = b""
    for i, m in enumerate(mails):
        out += f"From sender{i}@example.com Sat Nov 14 10:00:00 2026\n".encode()
        out += m.replace(b"\r\n", b"\n") + b"\n\n"
    return out


# --- 인코딩 ---


def test_euc_kr로_표시됐지만_cp949_글자가_있으면_cp949로_읽는다():
    # given: EUC-KR에는 없고 cp949에만 있는 글자 "똠"
    data = "똠방각하 회원님".encode("cp949")

    # when
    text = decode_bytes(data, "euc-kr")

    # then
    assert text == "똠방각하 회원님"


def test_인코딩_표시가_틀려도_UTF8_cp949_순서로_다시_시도한다():
    # given / when / then
    assert decode_bytes("가입".encode(), "us-ascii") == "가입"
    assert decode_bytes("가입".encode("cp949"), None) == "가입"
    assert decode_bytes(b"ok", "없는-charset") == "ok"


def test_RFC2047로_인코딩된_제목과_발신자_이름을_푼다():
    # given: euc-kr(실제 cp949) 제목, utf-8 발신자 이름
    data = raw_mail(
        subject=b64_word("[똠샵] 가입 완료", "cp949").replace("cp949", "euc-kr"),
        sender=f"{b64_word('똠샵', 'utf-8')} <help@ttom.example.com>",
    )

    # when
    mail = parse_mail(data)

    # then
    assert mail.subject == "[똠샵] 가입 완료"
    assert mail.sender == "help@ttom.example.com"


def test_인코딩_없이_8비트로_들어온_헤더도_읽는다():
    # given: 제목에 UTF-8 바이트가 그대로 들어간 메일
    data = raw_mail(subject="비밀번호 변경 안내")

    # when
    mail = parse_mail(data)

    # then
    assert mail.subject == "비밀번호 변경 안내"


def test_base64와_quoted_printable_본문을_푼다():
    # given
    b64 = raw_mail(body=base64.b64encode("본문 하나".encode()), cte="base64")
    qp = raw_mail(
        body=quopri.encodestring("본문 둘".encode("cp949")),
        content_type="text/plain; charset=ks_c_5601-1987",
        cte="quoted-printable",
    )

    # when / then
    assert parse_mail(b64).body_text == "본문 하나"
    assert parse_mail(qp).body_text == "본문 둘"


# --- 본문 ---


def multipart(*parts: tuple[str, str, bytes]) -> bytes:
    """(Content-Type, 추가 헤더, 본문) 목록으로 multipart/mixed 메일을 만든다."""
    body = b""
    for content_type, extra, payload in parts:
        body += b"--B\r\n" + f"Content-Type: {content_type}\r\n{extra}\r\n".encode() + payload
        body += b"\r\n"
    body += b"--B--\r\n"
    return raw_mail(body=body, content_type='multipart/mixed; boundary="B"')


def test_HTML만_있으면_스크립트와_스타일을_빼고_글자만_남긴다():
    # given
    html = (
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>회원&nbsp;가입을\n   환영합니다</p><script>alert(1)</script>"
        "<table><tr><td>아이디</td><td>hong</td></tr></table></body></html>"
    )
    data = raw_mail(body=html.encode(), content_type="text/html; charset=utf-8")

    # when
    body = parse_mail(data).body_text

    # then
    assert body == "회원 가입을 환영합니다\n\n아이디 hong"


def test_평문과_HTML이_함께_있으면_평문을_쓴다():
    # given
    data = multipart(
        ("text/plain; charset=utf-8", "", "평문 본문입니다".encode()),
        ("text/html; charset=utf-8", "", "<p>HTML 본문입니다</p>".encode()),
    )

    # when / then
    assert parse_mail(data).body_text == "평문 본문입니다"


def test_평문이_HTML보다_훨씬_짧으면_HTML을_쓴다():
    # given: "HTML로 보세요" 같은 짧은 평문
    long_html = "<p>" + "탈퇴가 완료되었습니다. " * 10 + "</p>"
    data = multipart(
        ("text/plain; charset=utf-8", "", "HTML로 보세요".encode()),
        ("text/html; charset=utf-8", "", long_html.encode()),
    )

    # when / then
    assert parse_mail(data).body_text.startswith("탈퇴가 완료되었습니다.")


def test_첨부파일은_본문에_넣지_않는다():
    # given: 본문 + 텍스트 첨부
    data = multipart(
        ("text/plain; charset=utf-8", "", "본문".encode()),
        (
            "text/plain; charset=utf-8",
            'Content-Disposition: attachment; filename="receipt.txt"\r\n',
            "첨부 내용".encode(),
        ),
    )

    # when / then
    assert parse_mail(data).body_text == "본문"


def test_보이지_않는_문자를_지우고_한글을_NFC로_맞춘다():
    # given: 자모 분리(NFD) 한글과 폭 없는 공백
    body = "\u200b가입﻿ 완료".replace("가", "가")
    data = raw_mail(body=body.encode())

    # when / then
    assert parse_mail(data).body_text == "가입 완료"


def test_본문은_자르지_않고_전체를_담는다():
    # given
    data = raw_mail(body=("줄\n" * 5000).encode())

    # when / then
    assert parse_mail(data).body_text.count("줄") == 5000


# --- 발신자·날짜·ID ---


def test_발신_도메인은_소문자로_맞춘다():
    # given / when
    mail = parse_mail(raw_mail())

    # then
    assert mail.sender == "no-reply@shop.example.com"
    assert mail.sender_domain == "shop.example.com"


def test_날짜는_시간대를_유지하고_시간대가_없으면_UTC로_본다():
    # given / when
    kst = parse_mail(raw_mail()).date
    unknown = parse_mail(raw_mail(date="Sat, 14 Nov 2026 01:00:00 -0000")).date

    # then
    assert kst == datetime(2026, 11, 14, 10, tzinfo=KST)
    assert unknown == datetime(2026, 11, 14, 1, tzinfo=UTC)


def test_Date가_없으면_처음_받은_서버의_Received_시각을_쓴다():
    # given: Received는 위에서부터 마지막 서버 → 처음 서버 순서
    data = raw_mail(
        date=None,
        headers=(
            "Received: from b by c; Sat, 14 Nov 2026 10:05:00 +0900",
            "Received: from a by b; Sat, 14 Nov 2026 10:01:00 +0900",
        ),
    )

    # when / then
    assert parse_mail(data).date == datetime(2026, 11, 14, 10, 1, tzinfo=KST)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"date": None}, "날짜"),
        ({"sender": None}, "발신"),
        ({"sender": "이름만"}, "발신"),
    ],
)
def test_날짜나_발신_주소가_없으면_MailParseError(kwargs, reason):
    # given
    data = raw_mail(**kwargs)

    # when / then
    with pytest.raises(MailParseError, match=reason):
        parse_mail(data)


def test_Message_ID가_없으면_원문_해시를_ID로_쓴다():
    # given
    data = raw_mail(message_id=None)

    # when
    first, second = parse_mail(data), parse_mail(data)

    # then
    assert first.id.startswith("sha256:")
    assert first.id == second.id


# --- MBOX 나누기 ---


def test_MBOX를_메일_단위로_나누고_From_이스케이프를_되돌린다():
    # given: 본문에 ">From "이 들어간 메일 2통
    first = raw_mail(body=b">From here\nline")
    data = mbox_of(first, raw_mail(message_id="<2@x>"))

    # when
    parts = list(iter_mbox(io.BytesIO(data)))

    # then
    assert len(parts) == 2
    assert b"\nFrom here\n" in parts[0][0]
    assert parts[-1][1] == len(data)


# --- 파일 소스와 가져오기 ---


@pytest.fixture
def mails():
    return [
        raw_mail(message_id="<1@x>"),
        raw_mail(message_id="<2@x>", subject="주문 완료"),
        raw_mail(message_id="<3@x>", subject="탈퇴 완료"),
    ]


def test_MBOX_파일을_가져온다(tmp_path, mails):
    # given
    path = tmp_path / "takeout.mbox"
    path.write_bytes(mbox_of(*mails))

    # when
    result = import_mails(FileMailSource([path]))

    # then
    assert [m.subject for m in result.mails] == ["가입을 환영합니다", "주문 완료", "탈퇴 완료"]


def test_EML_폴더와_zip_안의_MBOX_EML을_모두_가져온다(tmp_path, mails):
    # given: 폴더 안에 EML 1개 + zip(MBOX 1통, EML 1개, 맥 메타데이터)
    folder = tmp_path / "export"
    folder.mkdir()
    (folder / "a.eml").write_bytes(mails[0])
    with zipfile.ZipFile(folder / "takeout.zip", "w") as zf:
        zf.writestr("Takeout/메일/전체보관함.mbox", mbox_of(mails[1]))
        zf.writestr("more/c.eml", mails[2])
        zf.writestr("__MACOSX/more/._c.eml", b"junk")
        zf.writestr("readme.txt", b"ignore me")

    # when
    source = FileMailSource([folder])
    result = import_mails(source)

    # then
    assert source.file_count == 3
    assert {m.id for m in result.mails} == {"<1@x>", "<2@x>", "<3@x>"}


def test_확장자가_다르면_내용을_보고_MBOX인지_판단한다(tmp_path, mails):
    # given: 확장자 없는 MBOX
    path = tmp_path / "All mail"
    path.write_bytes(mbox_of(*mails))

    # when / then
    assert len(import_mails(FileMailSource([path])).mails) == 3


def test_메일_파일이_없으면_UnsupportedFileError(tmp_path):
    # given: 빈 폴더
    (tmp_path / "empty").mkdir()

    # when / then
    with pytest.raises(UnsupportedFileError):
        FileMailSource([tmp_path / "empty"])


def test_깨진_메일은_건너뛰고_나머지는_계속_가져온다(tmp_path, mails):
    # given: 가운데에 발신자 없는 메일
    path = tmp_path / "a.mbox"
    path.write_bytes(mbox_of(mails[0], raw_mail(sender=None), mails[1]))

    # when
    result = import_mails(FileMailSource([path]))

    # then
    assert len(result.mails) == 2
    assert [s.reason for s in result.stats.skipped] == ["발신 주소 없음"]
    assert result.stats.skipped[0].origin == "a.mbox#1"


def test_같은_Message_ID는_한_번만_가져온다(tmp_path, mails):
    # given: 같은 메일이 MBOX와 EML에 모두 있음
    (tmp_path / "a.mbox").write_bytes(mbox_of(*mails))
    (tmp_path / "dup.eml").write_bytes(mails[0])

    # when
    result = import_mails(FileMailSource([tmp_path / "a.mbox", tmp_path / "dup.eml"]))

    # then
    assert len(result.mails) == 3
    assert result.stats.duplicates == 1


def test_진행률은_바이트_단위로_전체_크기에서_끝난다(tmp_path, mails):
    # given
    path = tmp_path / "a.mbox"
    path.write_bytes(mbox_of(*mails))
    progress = []

    # when
    import_mails(FileMailSource([path]), on_progress=lambda d, t: progress.append((d, t)))

    # then
    size = path.stat().st_size
    assert progress[-1] == (size, size)


def test_취소를_요청하면_ImportCancelled를_던진다(tmp_path, mails):
    # given
    path = tmp_path / "a.mbox"
    path.write_bytes(mbox_of(*mails))

    # when / then
    with pytest.raises(ImportCancelled):
        import_mails(FileMailSource([path]), should_cancel=lambda: True)
