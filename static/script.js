document.addEventListener('DOMContentLoaded', () => {
    // 1. الإشعارات الطافية (تختفي تلقائياً)
    setTimeout(() => {
        document.querySelectorAll('.flash').forEach(el => {
            el.style.animation = 'fadeOutUp 0.5s forwards';
            setTimeout(() => el.remove(), 500); // حذف من الـ DOM لتخفيف الذاكرة
        });
    }, 4000);

    // 2. الترجمة
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

    // 3. القائمة الجانبية
    const menuBtn = document.getElementById('menu-toggle'), sideNav = document.getElementById('side-nav');
    if (menuBtn && sideNav) menuBtn.addEventListener('click', () => sideNav.classList.toggle('active'));

    // 4. طي الأقسام
    document.querySelectorAll('.accordion-header').forEach(acc => {
        acc.addEventListener('click', function() {
            const content = this.nextElementSibling;
            content.style.maxHeight = content.style.maxHeight ? null : content.scrollHeight + "px";
        });
    });

    // 5. لغز التسلسل العادي
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

    // 6. لغز الضغط المتكرر
    let clickCounts = {};
    document.querySelectorAll('.multi-click-word').forEach(word => {
        word.addEventListener('click', function() {
            let id = this.getAttribute('data-id');
            let targetClicks = parseInt(this.getAttribute('data-target') || 5);
            clickCounts[id] = (clickCounts[id] || 0) + 1;
            this.style.color = "var(--zone-3-gold)";
            this.style.textShadow = `0 0 ${clickCounts[id] * 2}px var(--zone-3-gold)`;
            this.style.transform = `scale(${1 + (clickCounts[id]*0.05)})`;
            if(clickCounts[id] >= targetClicks) window.location.href = `/multi_click/${id}`;
        });
    });

    // 7. تصدير الرخصة
    const exportBtn = document.getElementById('export-license');
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            html2canvas(document.querySelector("#license-card"), { useCORS: true, backgroundColor: "#1a1d24" }).then(canvas => {
                let link = document.createElement('a'); link.download = 'License.png'; link.href = canvas.toDataURL(); link.click();
            });
        });
    }
});
