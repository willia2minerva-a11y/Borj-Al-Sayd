document.addEventListener('DOMContentLoaded', () => {
    // 1. نظام الترجمة (يقلب النصوص فعلياً)
    const langBtn = document.getElementById('lang-toggle');
    let isEnglish = false;
    if(langBtn) {
        langBtn.addEventListener('click', () => {
            document.body.classList.toggle('ltr-mode');
            isEnglish = !isEnglish;
            document.querySelectorAll('.translatable').forEach(el => {
                el.innerText = isEnglish ? el.getAttribute('data-en') : el.getAttribute('data-ar');
            });
        });
    }

    // 2. القائمة والطي
    const menuBtn = document.getElementById('menu-toggle'), sideNav = document.getElementById('side-nav');
    if (menuBtn && sideNav) menuBtn.addEventListener('click', () => sideNav.classList.toggle('active'));

    document.querySelectorAll('.accordion-header').forEach(acc => {
        acc.addEventListener('click', function() {
            const content = this.nextElementSibling;
            content.style.maxHeight = content.style.maxHeight ? null : content.scrollHeight + "px";
        });
    });

    // 3. لغز التسلسل
    let currentSeq = 1;
    const totalWords = document.querySelectorAll('.secret-word').length;
    document.querySelectorAll('.secret-word').forEach(word => {
        word.addEventListener('click', function() {
            if (parseInt(this.getAttribute('data-order')) === currentSeq) {
                this.classList.add('glow-effect'); currentSeq++;
                if (currentSeq > totalWords) { alert('🎉 اكتشفت التسلسل السري!'); currentSeq = 1; }
            } else { currentSeq = 1; document.querySelectorAll('.secret-word').forEach(w => w.classList.remove('glow-effect')); }
        });
    });

    // 4. تصوير الرخصة
    const exportBtn = document.getElementById('export-license');
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            html2canvas(document.querySelector("#license-card"), { useCORS: true, backgroundColor: "#1a1d24" }).then(canvas => {
                let link = document.createElement('a'); link.download = 'License.png'; link.href = canvas.toDataURL(); link.click();
            });
        });
    }
});
