import tkinter as tk
import math
import time

class WordWatch(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Word Watch - 数字の代わりに単語で時間を表示")
        self.geometry("420x420")
        self.resizable(False, False)
        
        # 背景を黒くして高級感のある時計風に
        self.canvas = tk.Canvas(self, width=420, height=420, bg="#0a0a0a", highlightthickness=0)
        self.canvas.pack()
        
        self.draw_static_elements()
        self.update_clock()  # 初回描画 + 定期更新開始

    def draw_static_elements(self):
        # 外側のベゼル（金色の高級感）
        self.canvas.create_oval(30, 30, 390, 390, outline="#d4af37", width=25, fill="#1c1c1c")
        
        # 時計の文字盤本体（ダークグレー）
        self.canvas.create_oval(55, 55, 365, 365, outline="#333333", width=8, fill="#111111")
        
        # 文字盤の内側リング
        self.canvas.create_oval(70, 70, 350, 350, outline="#555555", width=3)
        
        # 12個の時間単語（数字の代わりに単語！）
        hour_words = ["TWELVE", "ONE", "TWO", "THREE", "FOUR", "FIVE",
                      "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN"]
        
        for i in range(12):
            angle = math.radians(i * 30 - 90)  # 12時を上にする
            # 文字を置く位置（少し内側）
            x = 210 + 115 * math.cos(angle)
            y = 210 + 115 * math.sin(angle)
            
            # 長い単語でも見やすいフォント
            self.canvas.create_text(x, y, text=hour_words[i],
                                    font=("Arial", 11, "bold"),
                                    fill="#f0d070", anchor="center")
        
        # 分刻みの目盛り（60本）
        for i in range(60):
            angle = math.radians(i * 6 - 90)
            if i % 5 == 0:
                # 5分ごと（時間位置）は少し長め・太め
                r1 = 137
                r2 = 153
                width = 3.5
            else:
                # 通常の分目盛り
                r1 = 143
                r2 = 153
                width = 1.5
            x1 = 210 + r1 * math.cos(angle)
            y1 = 210 + r1 * math.sin(angle)
            x2 = 210 + r2 * math.cos(angle)
            y2 = 210 + r2 * math.sin(angle)
            self.canvas.create_line(x1, y1, x2, y2, fill="#aaaaaa", width=width)
        
        # 中心のボルト（金色）
        self.canvas.create_oval(200, 200, 220, 220, fill="#d4af37", outline="#ffd700", width=4)

    def update_clock(self):
        # 前の針を削除
        self.canvas.delete("hands")
        
        now = time.localtime()
        
        # 時針（短め・太め）
        hour_angle = math.radians((now.tm_hour % 12) * 30 + now.tm_min * 0.5 - 90)
        hx = 210 + 75 * math.cos(hour_angle)
        hy = 210 + 75 * math.sin(hour_angle)
        self.canvas.create_line(210, 210, hx, hy, fill="#ffd700", width=9, capstyle=tk.ROUND, tag="hands")
        
        # 分針（長め・太め）
        min_angle = math.radians(now.tm_min * 6 + now.tm_sec * 0.1 - 90)
        mx = 210 + 110 * math.cos(min_angle)
        my = 210 + 110 * math.sin(min_angle)
        self.canvas.create_line(210, 210, mx, my, fill="#ffd700", width=6, capstyle=tk.ROUND, tag="hands")
        
        # 秒針（細め・赤）
        sec_angle = math.radians(now.tm_sec * 6 - 90)
        sx = 210 + 125 * math.cos(sec_angle)
        sy = 210 + 125 * math.sin(sec_angle)
        self.canvas.create_line(210, 210, sx, sy, fill="#ff4444", width=2, capstyle=tk.ROUND, tag="hands")
        
        # 中心の小さな円（針の基部）
        self.canvas.create_oval(204, 204, 216, 216, fill="#222222", outline="#d4af37", tag="hands")
        
        # 1秒ごとに更新
        self.after(1000, self.update_clock)


if __name__ == "__main__":
    app = WordWatch()
    app.mainloop()