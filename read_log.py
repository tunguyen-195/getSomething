
import sys

def read_log():
    try:
        with open("verification_result.txt", "r", encoding="utf-8", errors="replace") as f:
            print(f.read())
    except Exception as e:
        print(f"Error reading log: {e}")
        # Try cp1252
        try:
             with open("verification_result.txt", "r", encoding="cp1252", errors="replace") as f:
                print(f.read())
        except:
            pass

if __name__ == "__main__":
    read_log()
