import cv2
import numpy as np
import cvui
import utils

class ScrollableImageViewer:
    def __init__(self, win_name, im=None, height_thresh=600, show_scrollbar=True):
        self.win_name = win_name
        self.height_thresh = height_thresh
        self.show_scrollbar = show_scrollbar
        self.scroll_pos = [0]
        self.max_scroll = 0
        self.im = None
        self.initialized = False
        
        if im is not None:
            self.imshow(im)
    
    def imshow(self, im):
        if not self.initialized:
            cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
            cvui.init(self.win_name)
            self.initialized = True
        
        self.im = im
        self.max_scroll = max(0, im.shape[0] - self.height_thresh)
        self.scroll_pos[0] = min(self.scroll_pos[0], self.max_scroll)
        self._update_display()
    
    def _update_display(self):
        if self.im is None:
            return
        
        if self.max_scroll > 0:
            scroll_int = int(self.scroll_pos[0])
            roi = self.im[scroll_int:scroll_int + self.height_thresh, :]
        else:
            roi = self.im
        
        if self.max_scroll > 0 and self.show_scrollbar:
            ui_frame = np.zeros((20, roi.shape[1], 3), dtype=np.uint8)
            ui_frame[:] = (100,100,100)
            cvui.trackbar(ui_frame, 0, 0, roi.shape[1] , self.scroll_pos, 0, self.max_scroll, 1, '%d', 
                         cvui.TRACKBAR_HIDE_VALUE_LABEL|cvui.TRACKBAR_HIDE_LABELS)
            
            combined = np.vstack([ui_frame, roi])
            cv2.imshow(self.win_name, combined)
        else:
            cv2.imshow(self.win_name, roi)
        
        cvui.update()
    
    def update(self):
        self._update_display()

def scrollable_imshow(win_name, im, height_thresh=600, show_scrollbar=True):
    """OpenCV imshow-like function with scrolling capability"""
    if not hasattr(scrollable_imshow, 'viewers'):
        scrollable_imshow.viewers = {}
    
    if win_name not in scrollable_imshow.viewers:
        scrollable_imshow.viewers[win_name] = ScrollableImageViewer(win_name, height_thresh=height_thresh, show_scrollbar=show_scrollbar)
    
    scrollable_imshow.viewers[win_name].imshow(im)

def create_long_test_im():
    if not hasattr(create_long_test_im, 'random_sets'):
        rng = np.random.default_rng(42)
        create_long_test_im.random_sets = [
            rng.integers(0, 1000, 1000),
            rng.integers(0, 1000, 1000)
        ]
        create_long_test_im.current_set = 0
    
    create_long_test_im.current_set = 1 - create_long_test_im.current_set
    random_nums = create_long_test_im.random_sets[create_long_test_im.current_set]
    
    test_text = '\n'.join([f'Line {i+1} - Y position: {(i+1)*30} - Random Number: {random_nums[i]}' 
                          for i in range(1000)])
    
    return utils.draw_text_withnewline(test_text, (20, 20), color=(200, 200, 200), 
                                     bg_color=(30, 30, 30), font_scale=0.7, font_thickness=2)

if __name__ == '__main__':
    # Precreate two test images
    im1 = create_long_test_im()
    im2 = create_long_test_im()
    
    viewer = ScrollableImageViewer("Scrollable Image", im1, height_thresh=600, show_scrollbar=True)
    
    print("Use the scroll trackbar to navigate the image")
    print("Press ESC to exit")
    
    use_first = True
    while True:
        # Swap between precreated images
        current_im = im1 if use_first else im2
        viewer.imshow(current_im)
        viewer.update()
        use_first = not use_first
        
        key = cv2.waitKey(1)
        if key == 27:
            break
    
    cv2.destroyAllWindows()
