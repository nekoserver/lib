# tree-view向けミニキーボード（2026-11-09）

chat/app.mjsへ、既存の親window・許可オリジン検査を通した入力方式の切り替えと文字編集を追加。Cookieの保存はdynamicneko側で行い、現在の方式をconversation-controlsで渡す。Enterでの自動投稿なし。keyboard-input.mjsを新設し、生成処理にもハッシュ資産として追加した。生成appとconversation-embed.htmlを同時に配置する必要がある。

node --test test/chat_keyboard_test.mjs test/chat_console_form_test.mjs: 6件成功。sourceと生成appのnode --check成功。稼働中配信への上書き・pushは未実施。親側のウィンドウ/入力変更と検証の詳細は/root/dynamicneko/REPORT.dynamicneko.20261109.chat-window-keyboard.mdを参照。
