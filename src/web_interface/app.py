import os
import sys
import logging
import gradio as gr
from pathlib import Path
import json
import time
import requests
import datetime

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.speech_to_text.transcriber import Transcriber

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('web_interface.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class WebInterface:
    def __init__(self):
        """Initialize web interface components"""
        logger.info("Initializing components...")
        
        # Initialize transcriber with default model
        self.transcriber = Transcriber()
        logger.info("Initialized transcriber with default model")
        
        # Create Gradio interface
        self.interface = self._create_interface()
        logger.info("Created Gradio interface successfully")
        
    def _create_interface(self):
        """Create Gradio interface"""
        with gr.Blocks(title="Speech to Information") as interface:
            gr.Markdown("# Speech to Information")
            gr.Markdown("Upload an audio file to transcribe and analyze")
            
            with gr.Row():
                with gr.Column():
                    audio_input = gr.Audio(
                        label="Audio Input",
                        type="filepath"
                    )
                    language = gr.Radio(
                        choices=["vi"],
                        value="vi",
                        label="Language"
                    )
                    model = gr.Dropdown(
                        choices=list(self.transcriber.llm_processor.get_available_models().keys()),
                        value="gemma2:9b",
                        label="Model",
                        info="Chọn model để phân tích ngữ cảnh"
                    )
                    process_btn = gr.Button("Process Audio")
                    
                with gr.Column():
                    transcription = gr.Textbox(
                        label="Transcription",
                        lines=10
                    )
                    analysis = gr.Textbox(
                        label="Analysis",
                        lines=15
                    )
                    download_btn = gr.File(
                        label="Tải xuống kết quả phân tích",
                        visible=False
                    )
                    status_msg = gr.Textbox(
                        label="Trạng thái",
                        visible=False
                    )
                    
            def process_with_model(audio_file, lang, selected_model):
                # Set selected model
                self.transcriber.llm_processor.set_model(selected_model)
                # Process audio
                transcription, analysis = self.process_audio(audio_file, lang)
                
                # Create export directory if it doesn't exist
                export_dir = os.path.join(os.path.dirname(audio_file), "exports")
                os.makedirs(export_dir, exist_ok=True)

                # Generate filename with timestamp
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                export_path = os.path.join(export_dir, f"audio_analysis_{timestamp}.txt")

                # Write results to file
                try:
                    with open(export_path, "w", encoding="utf-8") as f:
                        f.write("=== TRANSCRIPTION ===\n\n")
                        f.write(transcription)
                        f.write("\n\n=== ANALYSIS ===\n\n")
                        f.write(analysis)
                    
                    return transcription, analysis, export_path, "File đã được tạo thành công!"
                except Exception as e:
                    logger.error(f"Error creating export file: {e}")
                    return transcription, analysis, None, f"Lỗi khi tạo file: {str(e)}"
                    
            process_btn.click(
                fn=process_with_model,
                inputs=[audio_input, language, model],
                outputs=[transcription, analysis, download_btn, status_msg]
            )
            
        return interface
        
    def process_audio(self, audio_file: str, language: str) -> tuple[str, str]:
        """Process audio file and return transcription and analysis"""
        try:
            logger.info(f"Processing audio file: {audio_file}")
            logger.info(f"Language: {language}")
            
            # Transcribe and analyze audio
            result = self.transcriber.transcribe(audio_file)
            
            # Extract transcription and analysis
            transcription = result["transcription"]
            analysis = result["analysis"]
            
            # Đảm bảo analysis luôn là dict
            if not isinstance(analysis, dict):
                analysis = {}
            
            # Format analysis for display
            try:
                # Check if analysis is a string (JSON string)
                if isinstance(analysis, str):
                    analysis = json.loads(analysis)
                
                # Ensure required fields exist
                if not isinstance(analysis, dict):
                    raise ValueError("Analysis must be a dictionary")
                
                # Initialize lines with basic info
                lines = [
                    "TÓM TẮT:",
                    analysis.get('summary', 'Không có tóm tắt'),
                    "",
                    "THÔNG TIN CHI TIẾT:"
                ]
                
                # Add context information if available
                context = analysis.get('context', {})
                if not isinstance(context, dict):
                    context = {}
                if context:
                    lines.extend([
                        f"- Chủ đề: {context.get('topic', 'N/A')}",
                        f"- Mục đích: {context.get('purpose', 'N/A')}",
                        f"- Giọng điệu: {context.get('tone', 'N/A')}",
                        f"- Lĩnh vực: {context.get('domain', 'N/A')}",
                        f"- Mức độ bảo mật: {context.get('privacy_level', 'N/A')}",
                        f"- Mối quan hệ: {context.get('relationships', 'N/A')}"
                    ])
                else:
                    lines.append("Không có thông tin chi tiết")
                
                lines.append("")
                
                # Add entities if available
                entities = analysis.get('entities', {})
                if entities:
                    # Add people
                    lines.append("NGƯỜI ĐƯỢC ĐỀ CẬP:")
                    for person in entities.get('people', []):
                        lines.append(f"- {person.get('name', 'N/A')} ({person.get('role', 'N/A')})" + 
                            (' [NHẠY CẢM: ' + person.get('sensitivity_reason', '') + ']' if person.get('is_sensitive') else '') +
                            f"\n  Ngữ cảnh: {person.get('context', 'N/A')}")
                    
                    # Add locations
                    lines.extend(["", "ĐỊA ĐIỂM:"])
                    for location in entities.get('locations', []):
                        lines.append(f"- {location.get('name', 'N/A')} ({location.get('type', 'N/A')})" + 
                            (f" - {location.get('address', '')}" if location.get('address') else '') +
                            (' [NHẠY CẢM: ' + location.get('sensitivity_reason', '') + ']' if location.get('is_sensitive') else '') +
                            f"\n  Ngữ cảnh: {location.get('context', 'N/A')}")
                    
                    # Add time
                    lines.extend(["", "THỜI GIAN:"])
                    for time in entities.get('time', []):
                        lines.append(f"- {time.get('value', 'N/A')} ({time.get('type', 'N/A')})" +
                            (' [NHẠY CẢM: ' + time.get('sensitivity_reason', '') + ']' if time.get('is_sensitive') else '') +
                            f"\n  Ngữ cảnh: {time.get('context', 'N/A')}")
                    
                    # Add contact info
                    contact = entities.get('contact', {})
                    if contact:
                        lines.extend(["", "THÔNG TIN LIÊN HỆ:"])
                        
                        # Phone
                        phone = contact.get('phone', {})
                        lines.append(f"- Số điện thoại: {phone.get('value', 'N/A')}")
                        if phone.get('is_sensitive'):
                            lines.append(f"  [NHẠY CẢM: {phone.get('sensitivity_reason', '')}]")
                        lines.append(f"  Ngữ cảnh: {phone.get('context', 'N/A')}")
                        
                        # Email
                        email = contact.get('email', {})
                        lines.extend(["", f"- Email: {email.get('value', 'N/A')}"])
                        if email.get('is_sensitive'):
                            lines.append(f"  [NHẠY CẢM: {email.get('sensitivity_reason', '')}]")
                        lines.append(f"  Ngữ cảnh: {email.get('context', 'N/A')}")
                        
                        # ID
                        id_info = contact.get('id', {})
                        lines.extend(["", f"- Định danh: {id_info.get('value', 'N/A')} ({id_info.get('type', 'N/A')})"])
                        if id_info.get('is_sensitive'):
                            lines.append(f"  [NHẠY CẢM: {id_info.get('sensitivity_reason', '')}]")
                        lines.append(f"  Ngữ cảnh: {id_info.get('context', 'N/A')}")
                
                # Add details if available
                details = analysis.get('details', {})
                if details:
                    # Requirements
                    lines.extend(["", "YÊU CẦU VÀ ĐIỀU KIỆN:"])
                    for req in details.get('requirements', []):
                        lines.append(f"- {req.get('content', 'N/A')}" + 
                            (' [NHẠY CẢM: ' + req.get('sensitivity_reason', '') + ']' if req.get('is_sensitive') else '') +
                            f"\n  Ngữ cảnh: {req.get('context', 'N/A')}")
                    
                    # Decisions
                    lines.extend(["", "QUYẾT ĐỊNH VÀ THỎA THUẬN:"])
                    for decision in details.get('decisions', []):
                        lines.append(f"- {decision.get('content', 'N/A')}" + 
                            (' [NHẠY CẢM: ' + decision.get('sensitivity_reason', '') + ']' if decision.get('is_sensitive') else '') +
                            f"\n  Ngữ cảnh: {decision.get('context', 'N/A')}")
                    
                    # Actions
                    lines.extend(["", "HÀNH ĐỘNG CẦN THỰC HIỆN:"])
                    for action in details.get('actions', []):
                        lines.append(f"- {action.get('content', 'N/A')}" + 
                            (' [NHẠY CẢM: ' + action.get('sensitivity_reason', '') + ']' if action.get('is_sensitive') else '') +
                            f"\n  Ngữ cảnh: {action.get('context', 'N/A')}")
                
                # Add key points
                lines.extend(["", "CÁC ĐIỂM CHÍNH:"])
                for point in analysis.get('key_points', []):
                    lines.append(f"- {point}")
                
                # Add remaining information
                lines.extend([
                    "",
                    "GHI CHÚ:",
                    analysis.get('notes', 'Không có ghi chú'),
                    "",
                    "TÓM TẮT BẢO MẬT:",
                    analysis.get('privacy_summary', 'Không có tóm tắt bảo mật'),
                    "",
                    f"CẢM XÚC: {analysis.get('sentiment', 'N/A')}"
                ])
                
                formatted_analysis = "\n".join(lines)
                return transcription, formatted_analysis
                
            except Exception as e:
                logger.error(f"Error formatting analysis: {e}")
                return transcription, str(analysis)
                
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            return str(e), str(e)
            
    def launch(self, **kwargs):
        """Launch the web interface"""
        self.interface.launch(**kwargs)

def main():
    """Main entry point"""
    interface = WebInterface()
    interface.launch(share=True)

if __name__ == "__main__":
    main() 