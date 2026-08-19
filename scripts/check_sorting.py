import requests
import sys

BASE_URL = "http://localhost:8000/api/v1/cases"

def check_sort(sort_by, order):
    print(f"Testing sort_by={sort_by}, order={order}...", end=" ")
    try:
        response = requests.get(f"{BASE_URL}?sort_by={sort_by}&order={order}")
        response.raise_for_status()
        cases = response.json()
        
        if not cases:
            print("No cases to sort.")
            return

        values = [c.get(sort_by) for c in cases]
        
        # Checking order
        # Filter out None for simple check or handle them
        # SQL default in cases.py is NULLS LAST for both ASC and DESC (explicitly set)
        
        # Verify NULLS LAST logic:
        # If ASC: [valid, valid, ..., None, None]
        # If DESC: [valid, valid, ..., None, None]
        
        non_none_values = [v for v in values if v is not None]
        none_count = values.count(None)
        
        # Check if Nones are at the end
        if none_count > 0:
            if values[-none_count:] != [None] * none_count:
                print(f"FAILED ❌ (NULLs not at end)")
                return

        # Check sorting of non-none values
        is_sorted = False
        if order == "asc":
            # For strings (titles), ensure case-insensitive comparison
            if sort_by == 'title':
                non_none_values_lower = [v.lower() for v in non_none_values]
                is_sorted = all(non_none_values_lower[i] <= non_none_values_lower[i+1] for i in range(len(non_none_values_lower)-1))
            else:
                is_sorted = all(non_none_values[i] <= non_none_values[i+1] for i in range(len(non_none_values)-1))
        else:
            if sort_by == 'title':
                non_none_values_lower = [v.lower() for v in non_none_values]
                is_sorted = all(non_none_values_lower[i] >= non_none_values_lower[i+1] for i in range(len(non_none_values_lower)-1))
            else:
                is_sorted = all(non_none_values[i] >= non_none_values[i+1] for i in range(len(non_none_values)-1))
            
        if is_sorted:
            print("OK ✅")
        else:
            print("FAILED ❌")
            print(f"Values: {values}")
            
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    check_sort("created_at", "desc")
    check_sort("created_at", "asc")
    check_sort("title", "asc")
    check_sort("title", "desc")
