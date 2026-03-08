document.addEventListener('DOMContentLoaded', () => {
    // طي الأخبار
    document.querySelectorAll('.accordion-header').forEach(acc => {
        acc.addEventListener('click', function() {
            const content = this.nextElementSibling;
            if (content.style.maxHeight) content.style.maxHeight = null;
            else content.style.maxHeight = content.scrollHeight + "px";
        });
    });

    // لغز التسلسل
    let currentSequence = 1;
    const totalWords = document.querySelectorAll('.secret-word').length;
    document.querySelectorAll('.secret-word').forEach(word => {
        word.addEventListener('click', function() {
            const order = parseInt(this.getAttribute('data-order'));
            if (order === currentSequence) {
                this.classList.add('glow-effect');
                currentSequence++;
                if (currentSequence > totalWords && totalWords > 0) {
                    alert('🎉 تسلسل صحيح! صور الشاشة وأرسلها للإدارة لأخذ النقاط.');
                    currentSequence = 1;
                }
            } else {
                currentSequence = 1;
                document.querySelectorAll('.secret-word').forEach(w => w.classList.remove('glow-effect'));
            }
        });
    });
});
