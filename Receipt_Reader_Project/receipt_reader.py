import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from datetime import datetime
from rapidfuzz import fuzz, process
import json
import psycopg

VALID_MERCHANTS = [
    "Waitrose",
    "Sainsburys",
    "Whole Foods",
    "Tesco",
    "Marks & Spencer",
    "John Lewis",
    "Uniqlo",
    "Charles Tyrwhitt",
    "Ikea",
    "Boots",
    "Amazon"
        ]
VALID_GROCERIES = {
    "Produce": [
        "Apples",
        "Bananas",
        "Blueberries",
        "Broccoli",
        "Cabbage",
        "Carrots",
        "Cauliflower",
        "Celery",
        "Garlic",
        "Green Beans",
        "Onions",
        "Oranges",
        "Peas",
        "Peppers",
        "Spinach",
        "Tomatoes"
    ],
    "Meat, Poultry, and Fish": [
        "Beef",
        "Bacon",
        "Chicken",
        "Chorizo",
        "Cod",
        "Ham",
        "Pork",
        "Salmon",
        "Sardines",
        "Sushi",
        "Turkey"
    ],
    "Carbohydrate Bases": [
        "Bread",
        "Oats",
        "Pasta",
        "Potatoes",
        "Rice"
    ],
    "Dairy/Related": [
        "Butter",
        "Cheese",
        "Ghee",
        "Milk",
        "Yogurt"
    ],
    "Pantry": [
        "Bouillon Cubes",
        "Chocolate",
        "Flour",
        "Sugar",
        "Teabags",
        "Yeast"
    ]
}
SUB_ITEMS = {
    "Linguine": "Pasta",
    "Spaghetti": "Pasta",
    "Tortiglioni": "Pasta",
    "Macaroni": "Pasta",
    "Penne": "Pasta",
    "Conchiglie": "Pasta",
    "Mozzarella": "Cheese",
    "Parmesan": "Cheese",
    "Baguette": "Bread",
    "Sourdough": "Bread"
}

FLATTENED_VALID_GROCERIES = []
for category_list in VALID_GROCERIES.values():
    FLATTENED_VALID_GROCERIES.extend(category_list)
FLATTENED_VALID_GROCERIES.extend(SUB_ITEMS.keys())

class Receipt:
    def __init__(self, merchant, date, purchases, purchase_total):
        self.merchant = merchant
        self.date = date
        self.purchases = purchases
        self.purchase_total = purchase_total

    @property
    def merchant(self):
        return self._merchant

    @merchant.setter
    def merchant(self, raw_merchant):
        if not raw_merchant:
            raise ValueError("No merchant name")

        self._merchant = self._categorise_merchant(raw_merchant)

    def _categorise_merchant(self, raw_merchant):
        raw_merchant = raw_merchant.title()
        best_match = process.extractOne(
            raw_merchant, 
            VALID_MERCHANTS, 
            scorer=fuzz.token_set_ratio,
            score_cutoff=75 
        )
        if best_match:
            return best_match[0]
        return "Unknown Merchant"

    @property
    def date(self):
        return self._date

    @date.setter
    def date(self, date):
        if not date:
            self._date = None
            return
            
        try:
            self._date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            self._date = date

    @property
    def purchases(self):
        return self._purchases

    @purchases.setter
    def purchases(self, raw_purchases):
        if not raw_purchases:
            raise ValueError("No purchases")
        self._purchases = self._categorise_purchases(raw_purchases)

    def _categorise_purchases(self, raw_purchases):

        purchases = []
        for row in raw_purchases:
            item = row.get("item")
            price = row.get("price")
            
            if not item or not price:
                continue

            if not isinstance(price, (int, float)) or price < 0:
                continue

            best_match = process.extractOne(
                item,
                FLATTENED_VALID_GROCERIES,
                scorer=fuzz.token_set_ratio,
                score_cutoff=50
            )
            if best_match:
                clean_name = best_match[0]
                if clean_name in SUB_ITEMS:
                    purchases.append({
                        "item": SUB_ITEMS[clean_name],
                        "price": price,
                        "category": self._get_category(SUB_ITEMS[clean_name])
                    })
                else:
                    purchases.append({
                        "item": clean_name, 
                        "price": price, 
                        "category": self._get_category(clean_name)
                    })
            else:
                purchases.append({
                    "item": item.title(), 
                    "price": price, 
                    "category": "Miscellaneous"
                })
        return purchases
    
    def _get_category(self, item):
        for category, items_list in VALID_GROCERIES.items():
            if item in items_list:
                return category
        return "Miscellaneous"

    @property
    def purchase_total(self):
        return self._purchase_total

    @purchase_total.setter
    def purchase_total(self, purchase_total):
        if isinstance(purchase_total, (int, float)) and purchase_total >= 0:
            self._purchase_total = float(purchase_total)
        else:
            self._purchase_total = None

load_dotenv()
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def process_receipt_image(image_file, user_id):
    receipt_image = client.files.upload(file=image_file)

    prompt = """
    Please read this receipt and extract the data into a strict JSON format. 
    Translate any receipt abbreviations into standard English terms, including merchant and item abbreviations.
    Format dates as YYYY-MM-DD.

    You must use this exact JSON structure:
    {
    "merchant": "Store Name",
    "date": "YYYY-MM-DD",
    "purchases": [
        {"item": "Item Name", "price": 0.00}
    ],
    "purchase_total": 0.00
    }
    """
    print("Sending to AI...")
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=[prompt, receipt_image],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        )
    )

    receipt_data = json.loads(response.text)
    my_receipt = Receipt(
        merchant=receipt_data.get("merchant"),
        date=receipt_data.get("date"),
        purchases=receipt_data.get("purchases"),
        purchase_total=receipt_data.get("purchase_total")
    )

    conn = psycopg.connect(os.getenv("DATABASE_URL"))

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM merchants WHERE name = %s", (my_receipt.merchant,))
        merchant_record = cur.fetchone()
        if not merchant_record:
            cur.execute("INSERT INTO merchants (name, type) VALUES (%s, %s) RETURNING id", (my_receipt.merchant, 'Grocery Store'))
            merchant_id = cur.fetchone()[0]
        else:
            merchant_id = merchant_record[0]
        cur.execute("""
            INSERT INTO receipts (user_id, merchant_id, purchase_total, receipt_date)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (user_id, merchant_id, my_receipt.purchase_total, my_receipt.date))
        receipt_id = cur.fetchone()[0]
        for purchase in my_receipt.purchases:
            cur.execute("""
                INSERT INTO receipt_items (receipt_id, category, item, price)
                VALUES (%s, %s, %s, %s);
            """, (receipt_id, purchase["category"], purchase["item"], purchase["price"]))

    conn.commit()
    conn.close()
