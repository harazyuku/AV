from datetime import date

from sqlalchemy import select

from app.main import Performer, Product, SessionLocal, init_db


HAIR_COLORS = ["黒", "茶", "金", "赤", "銀"]
HAIR_STYLES = ["ロング", "ショート", "ボブ", "ポニーテール", "ウェーブ"]
PERFORMER_TYPES = ["清楚系", "クール系", "お姉さん系", "かわいい系", "ギャル系"]
CLOTHING = ["スーツ", "制服", "ワンピース", "スポーツウェア", "私服"]
LOCATIONS = ["ホテル", "学校", "オフィス", "屋外", "自宅"]
MOODS = ["落ち着いた", "明るい", "クール", "ロマンチック", "活発"]


def mock_values(index: int) -> tuple[dict, list[dict]]:
    zero_index = index - 1
    color_index = zero_index // 20
    style_index = (zero_index // 4) % 5
    scene_index = zero_index % 4
    hair_color = HAIR_COLORS[color_index]
    hair_style = HAIR_STYLES[style_index]
    performer_type = PERFORMER_TYPES[(color_index + style_index + scene_index) % 5]
    clothing = CLOTHING[(style_index + scene_index) % 5]
    location = LOCATIONS[(color_index + scene_index) % 5]
    mood = MOODS[(color_index + style_index) % 5]
    people = 1 + ((color_index + style_index + scene_index) % 4)
    glasses = (zero_index % 3) == 0
    year = 2020 + (zero_index % 6)
    title = f"モック{index:03d} {hair_color}髪{hair_style} {clothing} {location} {people}人"
    description = f"{performer_type}の人物が登場する、{location}を舞台にした{mood}雰囲気の検索テスト用作品。"
    visual_analysis = {
        "summary": description,
        "people": people,
        "performers": [],
        "clothing": [clothing],
        "locations": [location],
        "mood": [mood],
        "keywords": [hair_color, hair_style, performer_type, clothing, location, mood],
    }
    attributes = {
        "schema_version": 10,
        "source": "mock",
        "source_id": f"mock-{index:03d}",
        "source_title": title,
        "source_metadata": {"product_code": f"MOCK-{index:03d}", "release_date": f"{year}-01-01"},
        "visual_analysis": visual_analysis,
        "summary": description,
        "人数": people,
        "衣装": [clothing],
        "場所": [location],
        "雰囲気": [mood],
        "キーワード": visual_analysis["keywords"],
    }
    performers = [
        {
            "name": f"モック出演者{index:03d}-{person_index + 1}",
            "type": performer_type,
            "hair_color": hair_color,
            "hair_style": hair_style,
            "glasses": glasses if person_index == 0 else False,
        }
        for person_index in range(people)
    ]
    return {
        "external_id": f"mock-{index:03d}",
        "title": title,
        "description": description,
        "release_date": date(year, 1 + (zero_index % 12), 1 + (zero_index % 27)),
        "fanza_url": f"https://example.invalid/mock-{index:03d}",
        "attributes": attributes,
    }, performers


def main() -> None:
    init_db()
    created = 0
    updated = 0
    with SessionLocal() as session:
        existing = {
            product.external_id: product
            for product in session.scalars(
                select(Product).where(Product.external_id.like("mock-%"))
            ).unique()
        }
        for index in range(1, 101):
            values, performers = mock_values(index)
            product = existing.get(values["external_id"])
            if product is None:
                product = Product(**values)
                session.add(product)
                created += 1
            else:
                for key, value in values.items():
                    if key != "external_id":
                        setattr(product, key, value)
                product.performers.clear()
                updated += 1
            product.performers = [Performer(**performer) for performer in performers]
        session.commit()
    print(f"mock seed complete: created={created}, updated={updated}, total=100")


if __name__ == "__main__":
    main()
