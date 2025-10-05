import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
import utils

def test_text_size_matches_drawing():
    test_cases = [
        "Single line",
        "Multi\nline\ntext", 
        "Short",
        "Very long text that should extend",
        "Mixed\nLength\nLines here\n herere ldkjf lasdhf 9iupasdf \n1\n2\n3"
    ]
    
    for text in test_cases:
        pos = (10, 10)
        font_scale = 0.6
        font_thickness = 1
        
        # Get predicted dimensions
        w_pred, h_pred = utils.get_text_size_withnewline(text, pos, font_scale, font_thickness)
        
        # Create image based on predicted size
        im = np.zeros((h_pred + 20, w_pred + 20, 3), dtype=np.uint8)
        
        # Draw predicted box in blue
        cv2.rectangle(im, pos, (pos[0] + w_pred, pos[1] + h_pred), (255, 0, 0), 1)
        
        # Draw text and get actual bounding box
        x1, y1, x2, y2 = utils.draw_text_withnewline(
            im, text, pos, color=(0, 255, 0), font_scale=font_scale, font_thickness=font_thickness
        )
        
        # Draw actual box in red
        cv2.rectangle(im, (x1, y1), (x2, y2), (0, 0, 255), 1)
        
        cv2.imshow(f"Test: {text.replace(chr(10), '\\n')}", im)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

if __name__ == "__main__":
    test_text_size_matches_drawing()
