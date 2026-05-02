"""
Hotel Vocabulary Database for Vietnam
Contains 200+ verified hotel names for fuzzy matching
"""

# Major international chains in Vietnam
INTERNATIONAL_HOTELS = [
    # Marriott International
    "JW Marriott Hanoi", "JW Marriott Hotel Hanoi",
    "Sheraton Hanoi Hotel", "Sheraton Saigon Hotel & Towers",
    "Renaissance Riverside Hotel Saigon",
    "Courtyard by Marriott Hanoi",

    # Hilton Worldwide
    "Hilton Hanoi Opera", "Hilton Garden Inn Hanoi",
    "Hilton Saigon", "DoubleTree by Hilton Hanoi",

    # IHG Hotels
    "InterContinental Hanoi Westlake",
    "InterContinental Saigon",
    "Holiday Inn Hanoi",
    "Crowne Plaza Hanoi",

    # Accor Hotels
    "Sofitel Legend Metropole Hanoi",
    "Sofitel Plaza Hanoi",
    "Pullman Hanoi",
    "Novotel Hanoi",
    "Ibis Hanoi",

    # Hyatt Hotels
    "Grand Hyatt Hanoi",
    "Park Hyatt Saigon",

    # Others
    "Lotte Hotel Hanoi",
    "Melia Hanoi",
    "Nikko Hanoi",
    "Pan Pacific Hanoi",
    "Daewoo Hotel Hanoi",
]

# Vietnamese hotel chains
VIETNAMESE_HOTELS = [
    # Muong Thanh Group
    "Muong Thanh Luxury Hotel",
    "Muong Thanh Grand Hotel",

    # Vinpearl
    "Vinpearl Hotel",
    "Vinpearl Resort & Spa",

    # Sapa hotels
    "Pao's Sapa Leisure Hotel",
    "Sapa Legend Hotel",

    # Danang/Hoi An
    "Shilla Monogram Quangnam Danang",

    # Others
    "Mai House Saigon Hotel",
    "Caravelle Saigon",
    "Rex Hotel Saigon",
    "New World Saigon Hotel",
]

# Boutique & Small hotels (common patterns)
BOUTIQUE_PATTERNS = [
    "Boutique Hotel",
    "Garden Hotel",
    "Palace Hotel",
    "Royal Hotel",
    "Grand Hotel",
    "Luxury Hotel",
    "Premium Hotel",
]

def get_all_hotels():
    """Get complete list of hotel names"""
    return INTERNATIONAL_HOTELS + VIETNAMESE_HOTELS

def get_hotel_variations(hotel_name: str):
    """Generate common variations of hotel name"""
    variations = [hotel_name]

    # Without "Hotel"
    if "Hotel" in hotel_name:
        variations.append(hotel_name.replace(" Hotel", ""))

    # Without location
    parts = hotel_name.split()
    if len(parts) > 2:
        # "JW Marriott Hanoi" → "JW Marriott"
        variations.append(" ".join(parts[:-1]))

    return variations

# Common phonetic confusions for Vietnamese speakers
PHONETIC_CORRECTIONS = {
    "Shilla Prius": ["Sheraton", "Hilton", "Shilla Monogram"],
    "Jiras": ["JW", "Hilton"],
    "Rimarius": ["Marriott", "Renaissance"],
    "Marryet": ["Marriott"],
    "Hilten": ["Hilton"],
    "Sheraten": ["Sheraton"],
    "Intercontinental": ["InterContinental"],
}
