// Galerie, slide show
// Version 2.0.9 : march 2005
// Authors : Regensburg and Guillion
// 'Find position of element' from a script by Peter-Paul Koch <http://www.quirksmode.org>
//Changes : 29/07/04 Cookie guided automatic slide show
//Changes : 03/08/04 Slide show automatic on if cookies not available
//Changes : 26/08/04 Excluded MSIE Mac from preloading image because of caching bug
//Changes : 19/09/04 Now an external js file
//Changes : 11/10/04 .html added
//Changes : 23/03/05 UTF8 Encoding

// findPosX : find x-position of element
function findPosX(obj)
{
var posx = 0;
if (obj.offsetParent)
    {
    while (obj.offsetParent)
        {
        posx += obj.offsetLeft
        obj = obj.offsetParent;
        }
    }
else if (obj.x)
    {
    posx += obj.x;
    }
return posx;
}

// jumpTo(num) : go to page (number) and jump to corresponding thumbnail in index frame
function jumpTo(num)
{
// Go to page (number)
location.href = "page_"+ num +".html";
// If frames
if (parent.index && parent.slide)
    {
// If to page 1, scroll index frame to start
    if (num == "1")
        {
        parent.index.scrollTo(0,0)
        }
// Else, find and scroll to x-position of thumbnail (number) in horizontal index frame
    else if (parent.index.document.images["thumb"+ num])
        {
        var x = findPosX(parent.index.document.images["thumb"+ num]);
            if (x > 0)
            {
            parent.index.scrollTo(x,0);
            }
        }
// Or, jump to anchor (number) in vertical index frame
    else if (parent.index.document.anchors["anchor"+ num])
        {
        parent.index.location.hash = "anchor"+ num;

        }
    }
}

// loadNextImage : pre-load next image
function loadNextImage(num)
{
if (document.images)
    {
    if (navigator.userAgent.indexOf("Opera") != -1)
        {
        nextimage = new Image();
        nextimage.src = "../mediafiles/l"+ num +".jpg";
        }
    else if (navigator.userAgent.indexOf("MSIE") != -1 && navigator.userAgent.indexOf("Mac") != -1)
        {
        ;
        }
    else
        {
        nextimage = new Image();
        nextimage.src = "../mediafiles/l"+ num +".jpg";
        }
    }
}

// Test the cookie value
//=> Name of the cookie, value to test
//<= true if the cookie value is equal to the value
function testCookie(cname, cvalue)
{
val=0;
if (document.cookie.length > 0)
    {
    offset=document.cookie.indexOf(cname+"=");
    if (offset != -1)
        {
        val=unescape(document.cookie.substring(offset+cname.length+1,cname.length+offset+2));
        }
    return val==cvalue;
    }
}

// jumpIfShow : do jump if slideshow is set with cookie
function jumpIfShow(num)
{
if (document.cookie.length > 0)
    {
    if (testCookie("galerieslide",1))
        {
        jumpTo(num);
        }
    }
else
    {
    jumpTo(num)
    }
}

// setShow : toggle slide show
function setShow(num)
{
if (document.cookie.length > 0)
    {
    if (testCookie("galerieslide",1))
        {
        document.cookie="galerieslide=0; path=/";
        location.reload();
        }
    else
        {
        document.cookie="galerieslide=1; path=/";
        jumpTo(num);
        }
    }
else
    {
    alert ("To be able to stop and start the slide show, please enable cookies in your web browser.\n\nIf cookies are enabled and you are viewing this gallery from a local disk (not from a web server), you may want to try a different browser. Some browsers, like Safari, do not use cookies locally.")
    }
}
    
// StartStopText : toggle start/stop text link
function StartStopText(num)
{
if (document.cookie.length > 0)
    {
    if (testCookie("galerieslide",1))
        {
        document.write('<a href="javascript:setShow('+ num +');">Stop slide show</a>');
        }
    else
        {
        document.write('<a href="javascript:setShow('+ num +');">Start slide show</a>');
        }
    }
else
    {
    document.write('<a href="javascript:setShow('+ num +');">Stop slide show</a>');
    }
}

// StartStopButton : toggle start/stop button
function StartStopButton(num)
{
if (document.cookie.length > 0)
    {
    if (testCookie("galerieslide",1))
        {
        document.write('<form action="javascript:setShow('+ num +');"><input type="submit" value="&nbsp;Stop slide show&nbsp;"></form>');
        }
    else
        {
        document.write('<form action="javascript:setShow('+ num +');"><input type="submit" value="&nbsp;Start slide show&nbsp;"></form>');
        }
    }
else
    {
    document.write('<form action="javascript:setShow('+ num +');"><input type="submit" value="&nbsp;Stop slide show&nbsp;"></form>');
    }
}

// StartStopImage : toggle start/stop image link
function StartStopImage(num)
{
if (document.cookie.length > 0)
    {
    if (testCookie("galerieslide",1))
        {
        document.write('<a href="javascript:setShow('+ num +');"><img name="btnstop" src="showstop.gif" border="0" alt="Stop slide show"</a>');
        }
    else
        {
        document.write('<a href="javascript:setShow('+ num +');"><img name="btnstart" src="showstart.gif" border="0" alt="Start slide show"</a>');
        stopbutton = new Image();
        stopbutton.src = "showstop.gif";
        }
    }
else
    {
    document.write('<a href="javascript:setShow('+ num +');"><img name="btnstop" src="showstop.gif" border="0" alt="Stop slide show"</a>');
    }
}
