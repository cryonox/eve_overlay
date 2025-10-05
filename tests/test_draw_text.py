import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
import utils

def test_draw_text_bounding_rect():
    im = np.zeros((400, 600, 3), dtype=np.uint8)
    
    test_cases = [
        ("Single line", (50, 50)),
        ("Multi\nline\ntext", (200, 50)),
        ("Short", (350, 50)),
        ("Very long text that should extend", (50, 150)),
        ("Mixed\nLength\nLines here", (50, 250))
    ]
    
    for text, pos in test_cases:
        x1, y1, x2, y2 = utils.draw_text_withnewline(
            im, text, pos, color=(0, 255, 0), bg_color=(50, 50, 50), 
            font_scale=0.6, font_thickness=1
        )
        
        cv2.rectangle(im, (x1, y1), (x2, y2), (255, 0, 0), 1)
        
        print(f"Text: '{text.replace(chr(10), '\\n')}' at {pos}")
        print(f"Bounding rect: ({x1}, {y1}) to ({x2}, {y2})")
        print()
    
    cv2.imshow("Text Bounding Test", im)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

def test_single_line_text():
    im = np.zeros((300, 500, 3), dtype=np.uint8)
    
    single_line_cases = [
        ("Hello World"),
        ("Short"),
        ("Very long single line text"),
        ("Test123")
    ]
    x = 50 
    y = 50
    for text in single_line_cases:
        x1, y1, x2, y2 = utils.draw_text(
            im, text, (x, y), color=(0, 255, 255), bg_color=(80, 80, 80),
            font_scale=0.6, font_thickness=1
        )
        
        cv2.rectangle(im, (x1, y1), (x2, y2), (255, 0, 255), 1)
        
        print(f"Single text: '{text}' at ({x}, {y})")
        print(f"Bounding rect: ({x1}, {y1}) to ({x2}, {y2})")
        print()
        
        y = y2
    
    cv2.imshow("Single Line Text Test", im)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    #utils.set_dpi_awareness()
    test_draw_text_bounding_rect()
    #test_single_line_text()
