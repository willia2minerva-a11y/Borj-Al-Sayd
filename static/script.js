document.addEventListener('DOMContentLoaded', () => {
    // تبديل اللغة (الاتجاه)
    const langBtn = document.getElementById('lang-toggle');
    if(langBtn) {
        langBtn.addEventListener('click', () => {
            document.body.classList.toggle('ltr-mode');
        });
    }

    // القائمة الجانبية
    const menuBtn = document.getElementById('menu-toggle');
    const sideNav = document.getElementById('side-nav');
    if (menuBtn && sideNav) menuBtn.addEventListener('click', () => sideNav.classList.toggle('active'));

    // طي الأخبار
    document.querySelectorAll('.accordion-header').forEach(acc => {
        acc.addEventListener('click', function() {
            const content = this.nextElementSibling;
            content.style.maxHeight = content.style.maxHeight ? null : content.scrollHeight + "px";
        });
    });

    // لغز التسلسل
    let currentSequence = 1;
    const totalWords = document.querySelectorAll('.secret-word').length;
    document.querySelectorAll('.secret-word').forEach(word => {
        word.addEventListener('click', function() {
            if (parseInt(this.getAttribute('data-order')) === currentSequence) {
                this.classList.add('glow-effect'); currentSequence++;
                if (currentSequence > totalWords) { alert('🎉 تسلسل صحيح!'); currentSequence = 1; }
            } else { currentSequence = 1; document.querySelectorAll('.secret-word').forEach(w => w.classList.remove('glow-effect')); }
        });
    });

    // تصدير الرخصة (تحويل HTML لصورة)
    const exportBtn = document.getElementById('export-license');
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            html2canvas(document.querySelector("#license-card"), { useCORS: true, backgroundColor: "#1a1d24" }).then(canvas => {
                let link = document.createElement('a');
                link.download = 'Hunter_License.png';
                link.href = canvas.toDataURL("image/png");
                link.click();
            });
        });
    }
});
