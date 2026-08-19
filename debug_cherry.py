
import sys
import os
import logging
import traceback

sys.path.append(os.getcwd())
logging.basicConfig(level=logging.INFO)

def debug():
    print("DEBUGGING CHERRY SUMMARIZER...")
    try:
        from src.services.cherry_summarizer import summarize_forensic
        
        # Test transcript
        transcript = """
        Người A: Alo, cho tôi đặt phòng nhé.
        Người B: Vâng, anh cần phòng loại nào ạ?
        Người A: Cho phòng VIP đi, giá bao nhiêu?
        Người B: 2 triệu một đêm anh nhé.
        Người A: OK chốt. SĐT tôi là 0912345678.
        """
        
        print("Calling summarize_forensic...")
        result = summarize_forensic(transcript, scenario="general_intelligence")
        print("Result:", result)
        
    except Exception as e:
        print("CAUGHT EXCEPTION:")
        traceback.print_exc()

if __name__ == "__main__":
    debug()
