from app.db.session import init_db, SessionLocal
from app.db.models import Shop, Customer, Item


def seed():
    init_db()
    with SessionLocal() as db:
        if db.query(Shop).first():
            print("Already seeded")
            return
        db.add(Shop(name="Sharma Kirana Store", language="hi-IN"))
        db.flush()
        sid = 1
        db.add_all([
            Customer(shop_id=sid, name="Ramesh Kumar", nicknames=["ramesh", "रमेश"], phone="9000000001"),
            Customer(shop_id=sid, name="Ramesh Gupta", nicknames=["ramesh", "रमेश"], phone="9000000002"),
            Customer(shop_id=sid, name="Sharma ji", nicknames=["sharma", "शर्मा"], phone="9000000003"),
            Customer(shop_id=sid, name="Sunita Deshmukh", nicknames=["sunita", "सुनीता"], phone="9000000004", preferred_language="mr-IN"),
            Customer(shop_id=sid, name="Priya Patel", nicknames=["priya", "प्रिया", "પ્રિયા"], phone="9000000005", preferred_language="gu-IN"),
            Customer(shop_id=sid, name="Anil Reddy", nicknames=["anil", "अनिल", "అనిల్"], phone="9000000006", preferred_language="te-IN"),
        ])
        db.add_all([
            Item(shop_id=sid, name="chawal", unit="kg", price=60, cost_price=50, stock_qty=40, reorder_level=10,
                 aliases=["rice", "चावल", "तांदूळ", "ચોખા"]),
            Item(shop_id=sid, name="biscuit", unit="packet", price=10, cost_price=8, stock_qty=24, reorder_level=10,
                 aliases=["बिस्किट", "बिस्कीट", "બિસ્કિટ"]),
            Item(shop_id=sid, name="atta", unit="kg", price=45, cost_price=38, stock_qty=50, reorder_level=15,
                 aliases=["flour", "आटा", "पीठ", "લોટ"]),
            Item(shop_id=sid, name="tel", unit="litre", price=150, cost_price=135, stock_qty=20, reorder_level=6,
                 aliases=["oil", "तेल", "તેલ"]),
            Item(shop_id=sid, name="cheeni", unit="kg", price=44, cost_price=40, stock_qty=35, reorder_level=10,
                 aliases=["sugar", "चीनी", "साखर", "ખાંડ"]),
            Item(shop_id=sid, name="chai patti", unit="packet", price=120, cost_price=100, stock_qty=15, reorder_level=5,
                 aliases=["tea", "चायपत्ती", "चहा पावडर", "ચા"]),
        ])
        db.commit()
        print("Seeded: 1 shop, 6 customers, 6 items")


if __name__ == "__main__":
    seed()